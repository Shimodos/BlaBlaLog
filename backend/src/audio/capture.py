"""WASAPI Loopback audio capture for Windows using PyAudioWPatch."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Optional

import numpy as np
import pyaudiowpatch as pyaudio

from src.utils.config import get_settings

logger = logging.getLogger(__name__)


class AudioCapture:
    """Captures system audio via WASAPI loopback on Windows.

    Streams audio into a ring buffer and exposes methods to read
    fixed-duration chunks or retrieve the last N seconds of audio.
    Audio is resampled to mono float32 at the target sample rate.
    """

    def __init__(
        self,
        device_index: Optional[int] = None,
        sample_rate: int | None = None,
    ) -> None:
        settings = get_settings()
        self._target_sr: int = sample_rate or settings.sample_rate
        self._device_index = device_index

        # Ring buffer stores float32 mono samples at target sample rate.
        # Default capacity: 3600 seconds (1 hour).
        self._max_seconds = 3600
        self._buffer: deque[np.ndarray] = deque()
        self._buffer_samples = 0
        self._buffer_lock = threading.Lock()

        # Blocking-read queue: stores chunks produced by the capture thread.
        self._chunk_queue: deque[np.ndarray] = deque()
        self._chunk_event = threading.Event()

        self._pa: Optional[pyaudio.PyAudio] = None
        self._stream: Optional[pyaudio.Stream] = None
        self._thread: Optional[threading.Thread] = None
        self._is_recording = False
        self._stop_event = threading.Event()

        # Source device properties (populated on start).
        self._src_sr: int = 0
        self._src_channels: int = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def sample_rate(self) -> int:
        return self._target_sr

    # ------------------------------------------------------------------
    # Device enumeration
    # ------------------------------------------------------------------

    @staticmethod
    def _fix_device_name(name: str) -> str:
        """Fix device names that PyAudio returns in the wrong encoding on Windows.

        PyAudio often returns device names encoded as latin-1 (bytes of cp1251).
        We try to recover the original Cyrillic/Unicode name.
        """
        try:
            # If name already has valid non-ASCII chars (e.g. Cyrillic), return as-is
            if any(ord(c) > 255 for c in name):
                return name
            # Try to re-encode from latin-1 → bytes → decode as cp1251 (Russian Windows)
            raw = name.encode("latin-1")
            return raw.decode("cp1251")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return name

    @staticmethod
    def list_devices() -> list[dict]:
        """List all audio devices reported by PyAudioWPatch."""
        pa = pyaudio.PyAudio()
        devices: list[dict] = []
        try:
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                devices.append(
                    {
                        "index": int(info["index"]),
                        "name": AudioCapture._fix_device_name(info["name"]),
                        "is_loopback": info.get("isLoopbackDevice", False),
                        "channels": int(info["maxInputChannels"]),
                        "default_sample_rate": int(info["defaultSampleRate"]),
                    }
                )
        finally:
            pa.terminate()
        return devices

    @staticmethod
    def list_loopback_devices() -> list[dict]:
        """Return only WASAPI loopback devices."""
        return [d for d in AudioCapture.list_devices() if d["is_loopback"]]

    # ------------------------------------------------------------------
    # Capture lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Open a WASAPI loopback stream and begin capturing into the ring buffer."""
        if self._is_recording:
            logger.warning("AudioCapture is already recording.")
            return

        self._pa = pyaudio.PyAudio()
        device_info = self._resolve_device(self._pa, self._device_index)

        self._src_sr = int(device_info["defaultSampleRate"])
        self._src_channels = int(device_info["maxInputChannels"])
        device_idx = int(device_info["index"])

        logger.info(
            "Opening WASAPI loopback: device=%s  sr=%d  ch=%d",
            device_info["name"],
            self._src_sr,
            self._src_channels,
        )

        frames_per_buffer = int(self._src_sr * 0.1)  # 100 ms chunks

        self._stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=self._src_channels,
            rate=self._src_sr,
            input=True,
            input_device_index=device_idx,
            frames_per_buffer=frames_per_buffer,
            stream_callback=self._stream_callback,
        )

        self._stop_event.clear()
        self._is_recording = True
        self._stream.start_stream()
        logger.info("Audio capture started.")

    def stop(self) -> None:
        """Stop the capture stream and release resources."""
        if not self._is_recording:
            return

        self._stop_event.set()
        self._is_recording = False

        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                logger.debug("Error closing stream", exc_info=True)
            self._stream = None

        if self._pa is not None:
            self._pa.terminate()
            self._pa = None

        # Wake up any blocked read_chunk callers.
        self._chunk_event.set()
        logger.info("Audio capture stopped.")

    # ------------------------------------------------------------------
    # Reading audio
    # ------------------------------------------------------------------

    def get_audio(self, duration_seconds: float) -> np.ndarray:
        """Return the last *duration_seconds* of captured audio.

        Returns a 1-D float32 numpy array at ``self.sample_rate``.
        If less audio is available, returns whatever is in the buffer.
        """
        needed = int(duration_seconds * self._target_sr)

        with self._buffer_lock:
            if not self._buffer:
                return np.array([], dtype=np.float32)

            all_audio = np.concatenate(list(self._buffer))

        if len(all_audio) > needed:
            return all_audio[-needed:]
        return all_audio

    def read_chunk(self, chunk_seconds: float = 2.0) -> np.ndarray:
        """Blocking read of the next *chunk_seconds* of audio.

        Accumulates data from the internal queue until the requested
        duration is reached, then returns a 1-D float32 array.
        Returns an empty array if capture is stopped while waiting.
        """
        needed = int(chunk_seconds * self._target_sr)
        collected: list[np.ndarray] = []
        collected_samples = 0

        while collected_samples < needed:
            if self._stop_event.is_set():
                break

            # Wait for data.
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

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "AudioCapture":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _stream_callback(self, in_data, frame_count, time_info, status):
        """PyAudio stream callback — runs on the audio thread."""
        if status:
            logger.debug("Stream callback status: %s", status)

        raw = np.frombuffer(in_data, dtype=np.float32)
        mono = self._to_mono(raw, self._src_channels)
        resampled = self._resample(mono, self._src_sr, self._target_sr)

        # Push into ring buffer.
        with self._buffer_lock:
            self._buffer.append(resampled)
            self._buffer_samples += len(resampled)

            # Trim to max capacity.
            max_samples = self._max_seconds * self._target_sr
            while self._buffer_samples > max_samples and self._buffer:
                removed = self._buffer.popleft()
                self._buffer_samples -= len(removed)

        # Push into chunk queue for read_chunk().
        self._chunk_queue.append(resampled)
        self._chunk_event.set()

        return (None, pyaudio.paContinue)

    @staticmethod
    def _to_mono(audio: np.ndarray, channels: int) -> np.ndarray:
        """Down-mix interleaved multi-channel audio to mono."""
        if channels <= 1:
            return audio
        # Reshape to (num_frames, channels) and average.
        frames = len(audio) // channels
        audio = audio[: frames * channels].reshape(frames, channels)
        return audio.mean(axis=1).astype(np.float32)

    @staticmethod
    def _resample(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
        """Resample audio using linear interpolation (numpy only)."""
        if src_sr == dst_sr:
            return audio
        if len(audio) == 0:
            return audio

        duration = len(audio) / src_sr
        target_len = int(duration * dst_sr)
        if target_len == 0:
            return np.array([], dtype=np.float32)

        indices = np.linspace(0, len(audio) - 1, target_len)
        return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)

    @staticmethod
    def _resolve_device(pa: pyaudio.PyAudio, device_index: Optional[int]) -> dict:
        """Find the loopback device to use.

        If *device_index* is ``None``, automatically pick the WASAPI
        loopback device that mirrors the default output.
        """
        if device_index is not None:
            return pa.get_device_info_by_index(device_index)

        # Try to find the loopback mirror of the default speakers.
        try:
            wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError:
            raise RuntimeError("WASAPI host API not available on this system.")

        default_output_idx = wasapi_info["defaultOutputDevice"]
        default_output = pa.get_device_info_by_index(default_output_idx)
        default_name: str = default_output["name"]

        logger.debug("Default WASAPI output: %s (idx=%d)", default_name, default_output_idx)

        # Iterate all devices and find a loopback whose name matches.
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if (
                info.get("isLoopbackDevice", False)
                and info["maxInputChannels"] > 0
                and default_name in info["name"]
            ):
                logger.info("Auto-selected loopback device: %s (idx=%d)", info["name"], i)
                return info

        # Fallback: pick the first loopback device available.
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("isLoopbackDevice", False) and info["maxInputChannels"] > 0:
                logger.warning(
                    "Could not match default output; falling back to: %s (idx=%d)",
                    info["name"],
                    i,
                )
                return info

        raise RuntimeError(
            "No WASAPI loopback device found. Make sure an audio output device is enabled."
        )
