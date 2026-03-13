"""Abstract base class for loopback (system audio) capture."""

from __future__ import annotations

import abc
import threading
from collections import deque
from typing import Optional

import numpy as np

from src.utils.config import get_settings


class LoopbackCapture(abc.ABC):
    """Base class for platform-specific system audio (loopback) capture.

    Subclasses must implement: _open_stream(), _close_stream(), list_devices().
    Audio data is pushed into the ring buffer via _push_audio().
    """

    def __init__(
        self,
        device_index: Optional[int] = None,
        sample_rate: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self._target_sr: int = sample_rate or settings.sample_rate
        self._device_index = device_index

        # Ring buffer — float32 mono at target sample rate, 1 hour max.
        self._max_seconds = 3600
        self._buffer: deque[np.ndarray] = deque()
        self._buffer_samples = 0
        self._buffer_lock = threading.Lock()

        # Chunk queue for blocking read_chunk().
        self._chunk_queue: deque[np.ndarray] = deque()
        self._chunk_event = threading.Event()

        self._is_recording = False
        self._stop_event = threading.Event()

    # --- Properties ---

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def sample_rate(self) -> int:
        return self._target_sr

    # --- Abstract methods (platform-specific) ---

    @abc.abstractmethod
    def _open_stream(self) -> None:
        """Open the platform-specific audio stream."""

    @abc.abstractmethod
    def _close_stream(self) -> None:
        """Close the platform-specific audio stream."""

    @staticmethod
    @abc.abstractmethod
    def list_devices() -> list[dict]:
        """Return available loopback devices for the platform."""

    # --- Lifecycle ---

    def start(self) -> None:
        if self._is_recording:
            return
        self._stop_event.clear()
        self._open_stream()
        self._is_recording = True

    def stop(self) -> None:
        if not self._is_recording:
            return
        self._stop_event.set()
        self._is_recording = False
        self._close_stream()
        self._chunk_event.set()

    # --- Reading audio ---

    def get_audio(self, duration_seconds: float) -> np.ndarray:
        """Return the last *duration_seconds* of captured audio (1-D float32)."""
        needed = int(duration_seconds * self._target_sr)
        with self._buffer_lock:
            if not self._buffer:
                return np.array([], dtype=np.float32)
            all_audio = np.concatenate(list(self._buffer))
        if len(all_audio) > needed:
            return all_audio[-needed:]
        return all_audio

    def read_chunk(self, chunk_seconds: float = 2.0) -> np.ndarray:
        """Blocking read of the next chunk of audio."""
        needed = int(chunk_seconds * self._target_sr)
        collected: list[np.ndarray] = []
        collected_samples = 0

        while collected_samples < needed:
            if self._stop_event.is_set():
                break
            self._chunk_event.wait(timeout=0.5)
            while self._chunk_queue:
                chunk = self._chunk_queue.popleft()
                collected.append(chunk)
                collected_samples += len(chunk)
                if collected_samples >= needed:
                    break
            self._chunk_event.clear()

        if not collected:
            return np.array([], dtype=np.float32)
        audio = np.concatenate(collected)
        return audio[:needed]

    # --- Context manager ---

    def __enter__(self) -> "LoopbackCapture":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    # --- Helpers for subclasses ---

    def _push_audio(self, mono_float32: np.ndarray) -> None:
        """Push a chunk of mono float32 audio into the ring buffer and chunk queue."""
        with self._buffer_lock:
            self._buffer.append(mono_float32)
            self._buffer_samples += len(mono_float32)
            max_samples = self._max_seconds * self._target_sr
            while self._buffer_samples > max_samples and self._buffer:
                removed = self._buffer.popleft()
                self._buffer_samples -= len(removed)
        self._chunk_queue.append(mono_float32)
        self._chunk_event.set()

    @staticmethod
    def _to_mono(audio: np.ndarray, channels: int) -> np.ndarray:
        """Down-mix interleaved multi-channel audio to mono."""
        if channels <= 1:
            return audio
        frames = len(audio) // channels
        audio = audio[:frames * channels].reshape(frames, channels)
        return audio.mean(axis=1).astype(np.float32)

    @staticmethod
    def _resample(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
        """Resample via linear interpolation."""
        if src_sr == dst_sr or len(audio) == 0:
            return audio
        duration = len(audio) / src_sr
        target_len = int(duration * dst_sr)
        if target_len == 0:
            return np.array([], dtype=np.float32)
        indices = np.linspace(0, len(audio) - 1, target_len)
        return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)

    @staticmethod
    def _fix_device_name(name: str) -> str:
        """Fix device names with wrong encoding on Windows (cp1251 via latin-1)."""
        try:
            if any(ord(c) > 255 for c in name):
                return name
            raw = name.encode("latin-1")
            return raw.decode("cp1251")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return name
