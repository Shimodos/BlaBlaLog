"""Microphone capture using sounddevice (PortAudio)."""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Optional

import numpy as np
import sounddevice as sd

from src.utils.config import get_settings

logger = logging.getLogger(__name__)


class MicrophoneCapture:
    """Captures audio from the default (or specified) microphone via sounddevice.

    Audio is stored in a ring buffer as mono float32 at the target sample rate.
    """

    def __init__(
        self,
        device_index: Optional[int] = None,
        sample_rate: int | None = None,
    ) -> None:
        settings = get_settings()
        self._sample_rate: int = sample_rate or settings.sample_rate
        self._device_index = device_index

        # Ring buffer — stores float32 mono chunks at target sample rate.
        # Default capacity: 3600 seconds (1 hour).
        self._max_seconds = 3600
        self._buffer: deque[np.ndarray] = deque()
        self._buffer_samples = 0
        self._buffer_lock = threading.Lock()

        # Queue for blocking read_chunk().
        self._chunk_queue: deque[np.ndarray] = deque()
        self._chunk_event = threading.Event()

        self._stream: Optional[sd.InputStream] = None
        self._is_recording = False
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    # ------------------------------------------------------------------
    # Device enumeration
    # ------------------------------------------------------------------

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

    @staticmethod
    def list_devices() -> list[dict]:
        """List available input (microphone) devices via sounddevice."""
        devices: list[dict] = []
        all_devices = sd.query_devices()

        for i, dev in enumerate(all_devices):
            if dev["max_input_channels"] > 0:
                devices.append(
                    {
                        "index": i,
                        "name": MicrophoneCapture._fix_device_name(dev["name"]),
                        "channels": dev["max_input_channels"],
                        "default_sample_rate": int(dev["default_samplerate"]),
                    }
                )
        return devices

    # ------------------------------------------------------------------
    # Capture lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Open a sounddevice InputStream and begin capturing to the ring buffer."""
        if self._is_recording:
            logger.warning("MicrophoneCapture is already recording.")
            return

        device = self._device_index
        if device is None:
            # Use the system default input device.
            device = sd.default.device[0]

        dev_info = sd.query_devices(device)
        src_channels = int(dev_info["max_input_channels"])
        device_name = dev_info["name"]

        logger.info(
            "Opening microphone: device=%s  sr=%d  ch=%d",
            device_name,
            self._sample_rate,
            src_channels,
        )

        self._stop_event.clear()

        # sounddevice handles resampling via PortAudio if the device's
        # native rate differs from the requested sample rate.
        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,  # request mono directly
            dtype="float32",
            device=device,
            blocksize=int(self._sample_rate * 0.1),  # 100 ms blocks
            callback=self._stream_callback,
        )
        self._stream.start()
        self._is_recording = True
        logger.info("Microphone capture started.")

    def stop(self) -> None:
        """Stop the microphone stream and release resources."""
        if not self._is_recording:
            return

        self._stop_event.set()
        self._is_recording = False

        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                logger.debug("Error closing mic stream", exc_info=True)
            self._stream = None

        # Wake any blocked read_chunk() callers.
        self._chunk_event.set()
        logger.info("Microphone capture stopped.")

    # ------------------------------------------------------------------
    # Reading audio
    # ------------------------------------------------------------------

    def get_audio(self, duration_seconds: float) -> np.ndarray:
        """Return the last *duration_seconds* of captured microphone audio.

        Returns a 1-D float32 numpy array at ``self.sample_rate``.
        If less audio is available, returns whatever is in the buffer.
        """
        needed = int(duration_seconds * self._sample_rate)

        with self._buffer_lock:
            if not self._buffer:
                return np.array([], dtype=np.float32)
            all_audio = np.concatenate(list(self._buffer))

        if len(all_audio) > needed:
            return all_audio[-needed:]
        return all_audio

    def read_chunk(self, chunk_seconds: float = 2.0) -> np.ndarray:
        """Blocking read of the next *chunk_seconds* of microphone audio.

        Accumulates data from the internal queue until the requested
        duration is reached, then returns a 1-D float32 array.
        Returns an empty array if capture is stopped while waiting.
        """
        needed = int(chunk_seconds * self._sample_rate)
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

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "MicrophoneCapture":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _stream_callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        """sounddevice InputStream callback — runs on the audio thread."""
        if status:
            logger.debug("Mic stream callback status: %s", status)

        # indata shape is (frames, 1) for mono — flatten to 1-D.
        mono = indata[:, 0].copy()

        # Push into ring buffer.
        with self._buffer_lock:
            self._buffer.append(mono)
            self._buffer_samples += len(mono)

            max_samples = self._max_seconds * self._sample_rate
            while self._buffer_samples > max_samples and self._buffer:
                removed = self._buffer.popleft()
                self._buffer_samples -= len(removed)

        # Push into chunk queue for read_chunk().
        self._chunk_queue.append(mono)
        self._chunk_event.set()
