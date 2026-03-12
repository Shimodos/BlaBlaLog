"""Real-time chunked transcription with VAD-driven segmentation."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Optional, Awaitable

import numpy as np

from src.transcription.engine import TranscriptionEngine
from src.audio.vad import VoiceActivityDetector
from src.utils.config import get_settings

logger = logging.getLogger(__name__)

# Overlap kept at the end of the buffer after a segment is finalized,
# so that the next segment has acoustic context at its start.
_OVERLAP_SECONDS = 0.5

# Minimum buffer length (in seconds) before attempting a partial transcription,
# to avoid wasting GPU cycles on tiny fragments.
_MIN_PARTIAL_SECONDS = 1.0


class StreamingTranscriber:
    """Feeds audio chunks through VAD and transcribes speech segments in real time.

    Callbacks
    ---------
    on_partial : async (text: str, start: float) -> None
        Called with interim (not yet finalized) transcription results while
        speech is still in progress.
    on_final : async (segment: dict) -> None
        Called when a segment is finalized. The dict contains keys
        ``text``, ``start``, ``end``, and ``confidence``.
    on_speaker : async (speaker_label: str, segment: dict) -> None
        Called after finalization if a speaker label is available.
    """

    def __init__(
        self,
        engine: TranscriptionEngine,
        vad: VoiceActivityDetector,
        on_partial: Optional[Callable[[str, float], Awaitable[None]]] = None,
        on_final: Optional[Callable[[dict], Awaitable[None]]] = None,
        on_speaker: Optional[Callable[[str, dict], Awaitable[None]]] = None,
    ) -> None:
        self._engine = engine
        self._vad = vad

        self._on_partial = on_partial
        self._on_final = on_final
        self._on_speaker = on_speaker

        settings = get_settings()
        self._sample_rate: int = settings.sample_rate

        # Accumulated audio since the last finalized segment.
        self._buffer: np.ndarray = np.array([], dtype=np.float32)

        # Time offset (in seconds) of the buffer start relative to
        # the beginning of the recording.
        self._offset: float = 0.0

        self._running: bool = False

        # All finalized segments collected during the session.
        self._segments: list[dict] = []

        # Track whether speech is currently in progress so we know
        # when a silence gap means "segment done".
        self._speech_active: bool = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Reset internal state and begin accepting audio chunks."""
        self._buffer = np.array([], dtype=np.float32)
        self._offset = 0.0
        self._segments = []
        self._speech_active = False
        self._running = True
        self._vad.reset()
        logger.info("StreamingTranscriber started.")

    async def feed(self, audio_chunk: np.ndarray) -> None:
        """Append *audio_chunk* and process through VAD + transcription.

        Parameters
        ----------
        audio_chunk:
            1-D float32 array at 16 kHz mono.
        """
        if not self._running:
            logger.warning("feed() called while transcriber is not running.")
            return

        if audio_chunk.size == 0:
            return

        # Accumulate audio.
        self._buffer = np.concatenate([self._buffer, audio_chunk])

        # Run VAD on the current buffer.
        vad_segments = self._vad.process(self._buffer)

        if vad_segments:
            last_seg = vad_segments[-1]
            last_seg_end_sample = int(last_seg["end"] * self._sample_rate)
            buffer_end_seconds = len(self._buffer) / self._sample_rate

            # Silence duration after the last detected speech segment.
            silence_after = buffer_end_seconds - last_seg["end"]

            if silence_after >= self._vad.min_silence_duration:
                # Speech followed by enough silence — finalize all VAD segments.
                await self._finalize_segments(vad_segments)

                # Trim buffer: keep a small overlap for acoustic context.
                overlap_samples = int(_OVERLAP_SECONDS * self._sample_rate)
                keep_from = max(0, last_seg_end_sample - overlap_samples)
                trimmed = len(self._buffer) - keep_from
                self._offset += keep_from / self._sample_rate
                self._buffer = self._buffer[keep_from:]
                self._speech_active = False
            else:
                # Speech still in progress — emit a partial result.
                self._speech_active = True
                await self._emit_partial()
        elif self._speech_active:
            # VAD found no segments but we were previously in speech.
            # Buffer may have drifted into pure silence — emit partial
            # from whatever we had.
            await self._emit_partial()

    async def stop(self) -> list[dict]:
        """Stop the transcriber and finalize any remaining audio.

        Returns all finalized segments from the session.
        """
        self._running = False

        # Transcribe whatever remains in the buffer.
        if len(self._buffer) >= int(_MIN_PARTIAL_SECONDS * self._sample_rate):
            remaining_segments = self._engine.transcribe(self._buffer)
            for seg in remaining_segments:
                final_seg = {
                    "text": seg["text"],
                    "start": round(seg["start"] + self._offset, 3),
                    "end": round(seg["end"] + self._offset, 3),
                    "confidence": seg["confidence"],
                }
                self._segments.append(final_seg)
                if self._on_final:
                    await self._on_final(final_seg)

        self._buffer = np.array([], dtype=np.float32)
        logger.info(
            "StreamingTranscriber stopped. Total segments: %d", len(self._segments)
        )
        return list(self._segments)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _finalize_segments(self, vad_segments: list[dict]) -> None:
        """Transcribe detected VAD segments and fire on_final callbacks."""
        for vad_seg in vad_segments:
            audio_slice = vad_seg["audio"]
            if audio_slice.size == 0:
                continue

            transcribed = self._engine.transcribe(audio_slice)

            for seg in transcribed:
                final_seg = {
                    "text": seg["text"],
                    "start": round(seg["start"] + self._offset + vad_seg["start"], 3),
                    "end": round(seg["end"] + self._offset + vad_seg["start"], 3),
                    "confidence": seg["confidence"],
                }
                self._segments.append(final_seg)

                if self._on_final:
                    await self._on_final(final_seg)

                if self._on_speaker:
                    # Speaker label is not determined here; downstream
                    # callers can attach diarization. Fire with empty label
                    # so the callback knows the segment is ready.
                    await self._on_speaker("", final_seg)

    async def _emit_partial(self) -> None:
        """Run a quick transcription on the current buffer for interim results."""
        if self._on_partial is None:
            return

        buffer_seconds = len(self._buffer) / self._sample_rate
        if buffer_seconds < _MIN_PARTIAL_SECONDS:
            return

        # Run transcription in a thread pool so we don't block the event loop.
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None, self._engine.transcribe, self._buffer
            )
        except Exception:
            logger.debug("Partial transcription failed", exc_info=True)
            return

        if result:
            combined_text = " ".join(seg["text"] for seg in result)
            await self._on_partial(combined_text, self._offset)
