"""Speaker diarization using pyannote-audio.

Gracefully handles the case when pyannote or its pretrained models are not
available (missing HuggingFace token, no network, etc.).  When the pipeline
cannot be loaded the class remains usable but ``diarize*`` methods return
empty results.
"""

from __future__ import annotations

import io
import os
import wave
import logging
from pathlib import Path
from typing import Any

import numpy as np

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Minimum audio length (in samples at 16 kHz) worth diarizing – roughly 0.5 s.
_MIN_DIARIZE_SAMPLES = 8_000

_PYANNOTE_MODEL = "pyannote/speaker-diarization-3.1"


class SpeakerDiarizer:
    """Wrapper around the *pyannote/speaker-diarization-3.1* pipeline.

    Parameters
    ----------
    num_speakers:
        Exact number of speakers, if known in advance.
    min_speakers:
        Minimum expected number of speakers.
    max_speakers:
        Maximum expected number of speakers.
    """

    def __init__(
        self,
        num_speakers: int | None = None,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
    ) -> None:
        self._pipeline: Any = None
        self._available: bool = False

        self._num_speakers = num_speakers
        self._min_speakers = min_speakers
        self._max_speakers = max_speakers

        self._load_pipeline()

    # ------------------------------------------------------------------
    # Pipeline loading
    # ------------------------------------------------------------------

    def _load_pipeline(self) -> None:
        """Attempt to load the pyannote pipeline.

        Sets ``self._available`` to *True* on success.  On failure the
        error is logged and the instance stays in a *degraded* state
        where every ``diarize*`` call returns an empty list.
        """
        try:
            from pyannote.audio import Pipeline  # type: ignore[import-untyped]
        except ImportError:
            logger.warning(
                "pyannote.audio is not installed – speaker diarization "
                "will be unavailable.  Install it with: "
                "pip install pyannote.audio"
            )
            return

        hf_token: str | None = os.environ.get("HF_TOKEN")

        try:
            if hf_token:
                logger.info(
                    "Loading %s with HF_TOKEN …", _PYANNOTE_MODEL
                )
                self._pipeline = Pipeline.from_pretrained(
                    _PYANNOTE_MODEL, use_auth_token=hf_token
                )
            else:
                logger.info(
                    "Loading %s without token (public access) …",
                    _PYANNOTE_MODEL,
                )
                self._pipeline = Pipeline.from_pretrained(_PYANNOTE_MODEL)

            self._available = True
            logger.info("Speaker diarization pipeline loaded successfully.")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to load pyannote pipeline (%s: %s). "
                "Speaker diarization will be unavailable.",
                type(exc).__name__,
                exc,
            )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Whether the diarization pipeline loaded successfully."""
        return self._available

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def diarize(
        self,
        audio: np.ndarray,
        sample_rate: int = 16_000,
    ) -> list[dict]:
        """Run speaker diarization on an in-memory audio array.

        Parameters
        ----------
        audio:
            1-D ``float32`` NumPy array of audio samples.
        sample_rate:
            Sample rate in Hz (default 16 000).

        Returns
        -------
        list[dict]
            Each dict has keys ``speaker`` (``str``), ``start`` (``float``,
            seconds), and ``end`` (``float``, seconds).
        """
        if not self._available:
            logger.warning(
                "diarize() called but pipeline is not available – "
                "returning empty result."
            )
            return []

        if audio is None or audio.ndim == 0 or audio.size < _MIN_DIARIZE_SAMPLES:
            logger.debug(
                "Audio too short for diarization (%s samples).",
                0 if audio is None else getattr(audio, "size", 0),
            )
            return []

        pyannote_input = _audio_to_pyannote(audio, sample_rate)
        return self._run_pipeline(pyannote_input)

    def diarize_file(self, audio_path: str | Path) -> list[dict]:
        """Run speaker diarization on an audio file.

        Parameters
        ----------
        audio_path:
            Path to a WAV / FLAC / MP3 file readable by ``pyannote``.

        Returns
        -------
        list[dict]
            Same format as :meth:`diarize`.
        """
        if not self._available:
            logger.warning(
                "diarize_file() called but pipeline is not available – "
                "returning empty result."
            )
            return []

        audio_path = Path(audio_path)
        if not audio_path.is_file():
            logger.error("Audio file not found: %s", audio_path)
            return []

        return self._run_pipeline(str(audio_path))

    def merge_with_transcription(
        self,
        diarization: list[dict],
        segments: list[dict],
    ) -> list[dict]:
        """Merge diarization results with Whisper transcription segments.

        For each transcription segment the speaker with the **maximum
        temporal overlap** is assigned.

        Parameters
        ----------
        diarization:
            Output of :meth:`diarize` or :meth:`diarize_file`.
        segments:
            Whisper-style segment dicts with at least ``text``, ``start``,
            ``end``, and optionally ``confidence``.

        Returns
        -------
        list[dict]
            Enriched copies of *segments* with an added ``speaker_label``
            key (e.g. ``"SPEAKER_00"`` or ``"Unknown"``).
        """
        if not segments:
            return []

        enriched: list[dict] = []
        for seg in segments:
            speaker = self._find_best_speaker(
                seg.get("start", 0.0),
                seg.get("end", 0.0),
                diarization,
            )
            enriched.append(
                {
                    "text": seg.get("text", ""),
                    "start": seg.get("start", 0.0),
                    "end": seg.get("end", 0.0),
                    "confidence": seg.get("confidence", 0.0),
                    "speaker_label": speaker,
                }
            )

        return enriched

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_pipeline(self, audio_input: Any) -> list[dict]:
        """Execute the pyannote pipeline and convert output to plain dicts."""
        params: dict[str, Any] = {}
        if self._num_speakers is not None:
            params["num_speakers"] = self._num_speakers
        if self._min_speakers is not None:
            params["min_speakers"] = self._min_speakers
        if self._max_speakers is not None:
            params["max_speakers"] = self._max_speakers

        try:
            annotation = self._pipeline(audio_input, **params)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Diarization pipeline failed (%s: %s).",
                type(exc).__name__,
                exc,
            )
            return []

        results: list[dict] = []
        for turn, _, speaker in annotation.itertracks(yield_label=True):
            results.append(
                {
                    "speaker": str(speaker),
                    "start": round(turn.start, 3),
                    "end": round(turn.end, 3),
                }
            )

        logger.info(
            "Diarization complete: %d turns, %d unique speakers.",
            len(results),
            len({r["speaker"] for r in results}),
        )
        return results

    @staticmethod
    def _find_best_speaker(
        seg_start: float,
        seg_end: float,
        diarization: list[dict],
    ) -> str:
        """Return the speaker label with maximum overlap, or ``"Unknown"``."""
        if not diarization:
            return "Unknown"

        overlap_by_speaker: dict[str, float] = {}
        for d in diarization:
            overlap_start = max(seg_start, d["start"])
            overlap_end = min(seg_end, d["end"])
            overlap = max(0.0, overlap_end - overlap_start)
            if overlap > 0:
                speaker = d["speaker"]
                overlap_by_speaker[speaker] = (
                    overlap_by_speaker.get(speaker, 0.0) + overlap
                )

        if not overlap_by_speaker:
            return "Unknown"

        return max(overlap_by_speaker, key=overlap_by_speaker.get)  # type: ignore[arg-type]


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _audio_to_pyannote(
    audio: np.ndarray,
    sample_rate: int,
) -> dict[str, Any]:
    """Convert a NumPy float32 array to a pyannote-compatible input.

    Pyannote pipelines accept a ``dict`` with keys ``"waveform"``
    (``torch.Tensor`` of shape ``(channel, time)``) and
    ``"sample_rate"`` (``int``).  We try the torch path first; if
    torch is unavailable we fall back to an in-memory WAV file that
    pyannote can also read.
    """
    # Ensure float32 and 1-D
    audio = np.asarray(audio, dtype=np.float32).ravel()

    try:
        import torch

        waveform = torch.from_numpy(audio).unsqueeze(0)  # (1, T)
        return {"waveform": waveform, "sample_rate": sample_rate}
    except ImportError:
        pass

    # Fallback: write an in-memory WAV and return the path-like BytesIO.
    # pyannote can load from file-like objects via soundfile/torchaudio,
    # but the safest portable route is returning the bytes via a dict
    # after converting to int16 WAV.
    logger.debug(
        "torch not available; falling back to in-memory WAV for pyannote."
    )
    return _audio_to_memory_wav(audio, sample_rate)


def _audio_to_memory_wav(
    audio: np.ndarray,
    sample_rate: int,
) -> str:
    """Write *audio* to a temporary WAV file and return its path.

    We use a temporary file because pyannote's ``Pipeline.__call__``
    reliably accepts file paths but not arbitrary file-like objects
    in all backends.
    """
    import tempfile

    # Convert float32 [-1, 1] to int16
    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    try:
        with wave.open(tmp, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(pcm.tobytes())
        return tmp.name
    except Exception:
        # Clean up on failure
        tmp.close()
        os.unlink(tmp.name)
        raise
