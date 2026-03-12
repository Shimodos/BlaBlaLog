"""Faster-whisper transcription wrapper with automatic model management."""

from __future__ import annotations

import math
import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

# Minimum audio length (in samples at 16 kHz) that faster-whisper can process.
_MIN_AUDIO_SAMPLES = 400  # ~25 ms


def _resolve_device(device: str) -> tuple[str, str]:
    """Return (device, compute_type) based on the requested device string.

    ``"auto"`` probes for CUDA via PyTorch and falls back to CPU.
    """
    if device == "auto":
        try:
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            logger.debug("PyTorch not installed; defaulting to CPU")
            device = "cpu"

    compute_type = "float16" if device == "cuda" else "int8"
    return device, compute_type


class TranscriptionEngine:
    """High-level wrapper around ``faster_whisper.WhisperModel``.

    Parameters
    ----------
    model_size:
        Whisper model variant (``"tiny"``, ``"base"``, ``"small"``,
        ``"medium"``, ``"large-v2"``, etc.).  The model weights are
        downloaded automatically on first use.
    device:
        ``"cuda"``, ``"cpu"``, or ``"auto"`` (default).  When ``"auto"``,
        CUDA availability is checked via ``torch.cuda.is_available()``.
    language:
        Default language code for transcription (e.g. ``"ru"``).
    """

    def __init__(
        self,
        model_size: str = "medium",
        device: str = "auto",
        language: str = "ru",
    ) -> None:
        resolved_device, compute_type = _resolve_device(device)

        self._model_size = model_size
        self._device = resolved_device
        self._language = language

        logger.info(
            "Loading WhisperModel %s on %s (compute_type=%s)",
            model_size,
            resolved_device,
            compute_type,
        )

        from faster_whisper import WhisperModel

        self._model: WhisperModel = WhisperModel(
            model_size,
            device=resolved_device,
            compute_type=compute_type,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def model_size(self) -> str:
        return self._model_size

    @property
    def device(self) -> str:
        return self._device

    @property
    def language(self) -> str:
        return self._language

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
        beam_size: int = 1,
        vad_filter: bool = True,
    ) -> list[dict]:
        """Transcribe *audio* and return a list of segment dicts.

        Each dict contains:

        * ``text``  — transcribed text (``str``)
        * ``start`` — segment start in seconds (``float``)
        * ``end``   — segment end in seconds (``float``)
        * ``confidence`` — average probability in 0-1 range (``float``)

        Parameters
        ----------
        audio:
            1-D NumPy array of float32 samples at 16 kHz.
        language:
            Override the default language for this call.
        beam_size:
            Beam search width. 1 = greedy (fast), 5 = accurate (slow).
        vad_filter:
            Use Whisper's built-in Silero VAD to skip silence.
        """
        if not _is_valid_audio(audio):
            return []

        lang = language or self._language
        # "auto" means let Whisper auto-detect — pass None
        if lang == "auto":
            lang = None

        segments, _info = self._model.transcribe(
            audio,
            language=lang,
            beam_size=beam_size,
            vad_filter=vad_filter,
        )

        results: list[dict] = []
        for seg in segments:
            results.append(
                {
                    "text": seg.text.strip(),
                    "start": round(seg.start, 3),
                    "end": round(seg.end, 3),
                    "confidence": _logprob_to_prob(seg.avg_logprob),
                }
            )

        return results

    def transcribe_multilingual(
        self,
        audio: np.ndarray,
        beam_size: int = 1,
        vad_filter: bool = True,
        chunk_seconds: float = 30.0,
    ) -> list[dict]:
        """Transcribe audio with per-chunk language detection.

        Splits audio into chunks of *chunk_seconds* and transcribes each
        with ``language=None`` so Whisper auto-detects the language per chunk.
        This handles mid-conversation language switches (e.g. Russian → English).
        """
        if not _is_valid_audio(audio):
            return []

        sample_rate = 16000
        chunk_samples = int(chunk_seconds * sample_rate)
        total_samples = len(audio)

        if total_samples <= chunk_samples:
            # Short audio — single pass
            return self._transcribe_chunk(audio, 0.0, beam_size, vad_filter)

        results: list[dict] = []
        offset = 0
        while offset < total_samples:
            chunk = audio[offset : offset + chunk_samples]
            time_offset = offset / sample_rate
            chunk_results = self._transcribe_chunk(
                chunk, time_offset, beam_size, vad_filter
            )
            results.extend(chunk_results)
            offset += chunk_samples

        return results

    def _transcribe_chunk(
        self,
        audio: np.ndarray,
        time_offset: float,
        beam_size: int,
        vad_filter: bool,
    ) -> list[dict]:
        """Transcribe a single chunk with auto language detection."""
        if not _is_valid_audio(audio):
            return []

        segments, info = self._model.transcribe(
            audio,
            language=None,  # auto-detect per chunk
            beam_size=beam_size,
            vad_filter=vad_filter,
        )

        lang = info.language
        results: list[dict] = []
        for seg in segments:
            results.append(
                {
                    "text": seg.text.strip(),
                    "start": round(seg.start + time_offset, 3),
                    "end": round(seg.end + time_offset, 3),
                    "confidence": _logprob_to_prob(seg.avg_logprob),
                    "language": lang,
                }
            )
        return results

    def detect_language(
        self,
        audio: np.ndarray,
    ) -> tuple[str, float]:
        """Detect the spoken language in *audio*.

        Returns
        -------
        (language_code, probability)
            E.g. ``("en", 0.97)``.

        Raises
        ------
        ValueError
            If the audio is empty or too short for detection.
        """
        if not _is_valid_audio(audio):
            raise ValueError(
                "Audio is empty or too short for language detection."
            )

        # faster-whisper exposes language detection on the model directly.
        # We need to extract the log-mel spectrogram first.
        from faster_whisper.audio import decode_audio  # noqa: F401
        from faster_whisper.transcribe import Tokenizer  # noqa: F401

        # The model's internal feature extractor expects the raw audio.
        # Use `transcribe` with a very short segment to trigger detection,
        # or call the lower-level API when available.
        _segments, info = self._model.transcribe(
            audio,
            language=None,  # force auto-detection
            beam_size=1,
            vad_filter=False,
        )
        # We must consume the generator for `info` to be populated.
        # Consuming one segment is enough; we discard the rest.
        for _ in _segments:
            break

        return info.language, round(info.language_probability, 4)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _logprob_to_prob(avg_logprob: float) -> float:
    """Convert an average log-probability to a 0-1 confidence score."""
    try:
        prob = math.exp(avg_logprob)
    except OverflowError:
        prob = 1.0
    return round(max(0.0, min(1.0, prob)), 4)


def _is_valid_audio(audio: np.ndarray) -> bool:
    """Return ``True`` if *audio* has enough samples to process."""
    if audio is None:
        return False
    if audio.ndim == 0 or audio.size < _MIN_AUDIO_SAMPLES:
        return False
    return True
