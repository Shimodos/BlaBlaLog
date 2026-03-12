"""Audio mixing and channel management for system + microphone inputs."""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from src.audio.capture import AudioCapture
from src.audio.microphone import MicrophoneCapture

logger = logging.getLogger(__name__)


class AudioMixer:
    """Mixes system audio (WASAPI loopback) and microphone input, or keeps them separate.

    When both sources are provided, ``get_mixed_audio`` returns a mono mix
    normalized to matching levels. Either source can be ``None`` for
    single-source operation.
    """

    def __init__(
        self,
        system_capture: Optional[AudioCapture] = None,
        mic_capture: Optional[MicrophoneCapture] = None,
    ) -> None:
        self._system = system_capture
        self._mic = mic_capture

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start all available capture sources."""
        if self._system is not None:
            self._system.start()
            logger.info("System audio capture started via mixer.")
        if self._mic is not None:
            self._mic.start()
            logger.info("Microphone capture started via mixer.")

    def stop(self) -> None:
        """Stop all capture sources."""
        if self._system is not None:
            self._system.stop()
            logger.info("System audio capture stopped via mixer.")
        if self._mic is not None:
            self._mic.stop()
            logger.info("Microphone capture stopped via mixer.")

    # ------------------------------------------------------------------
    # Audio retrieval
    # ------------------------------------------------------------------

    def get_mixed_audio(self, duration_seconds: float) -> np.ndarray:
        """Return a mono mix of system and microphone audio.

        Both signals are peak-normalized to the same level before mixing.
        Returns a 1-D float32 array at 16 kHz.

        If only one source is available, returns that source's audio.
        If neither is available, returns an empty array.
        """
        sys_audio = self._get_source_audio(self._system, duration_seconds)
        mic_audio = self._get_source_audio(self._mic, duration_seconds)

        has_sys = sys_audio.size > 0
        has_mic = mic_audio.size > 0

        if has_sys and has_mic:
            # Ensure both arrays have the same length.
            target_len = max(len(sys_audio), len(mic_audio))
            sys_audio = _pad_or_trim(sys_audio, target_len)
            mic_audio = _pad_or_trim(mic_audio, target_len)

            # Normalize both to matching peak levels.
            sys_norm = _peak_normalize(sys_audio)
            mic_norm = _peak_normalize(mic_audio)

            # Average the two signals.
            mixed = (sys_norm + mic_norm) * 0.5
            return mixed.astype(np.float32)

        if has_sys:
            return sys_audio
        if has_mic:
            return mic_audio

        return np.array([], dtype=np.float32)

    def get_system_audio(self, duration_seconds: float) -> np.ndarray:
        """Return system (loopback) audio only.

        Returns a 1-D float32 array at 16 kHz, or an empty array if
        no system capture is configured.
        """
        return self._get_source_audio(self._system, duration_seconds)

    def get_mic_audio(self, duration_seconds: float) -> np.ndarray:
        """Return microphone audio only.

        Returns a 1-D float32 array at 16 kHz, or an empty array if
        no microphone capture is configured.
        """
        return self._get_source_audio(self._mic, duration_seconds)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "AudioMixer":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_source_audio(
        source: Optional[AudioCapture | MicrophoneCapture],
        duration_seconds: float,
    ) -> np.ndarray:
        """Safely read audio from a capture source, returning empty on failure."""
        if source is None:
            return np.array([], dtype=np.float32)
        try:
            return source.get_audio(duration_seconds)
        except Exception:
            logger.debug("Failed to read from audio source", exc_info=True)
            return np.array([], dtype=np.float32)


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _peak_normalize(audio: np.ndarray) -> np.ndarray:
    """Normalize audio so that the peak amplitude is 1.0.

    Silence (all zeros) is returned unchanged to avoid division by zero.
    """
    peak = np.max(np.abs(audio))
    if peak < 1e-8:
        return audio
    return audio / peak


def _pad_or_trim(audio: np.ndarray, target_len: int) -> np.ndarray:
    """Pad with zeros or trim to *target_len* samples."""
    if len(audio) >= target_len:
        return audio[:target_len]
    return np.pad(audio, (0, target_len - len(audio)), mode="constant")
