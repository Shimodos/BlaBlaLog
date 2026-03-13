"""PulseAudio monitor loopback capture for Linux."""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import sounddevice as sd

from src.audio.loopback.base import LoopbackCapture

logger = logging.getLogger(__name__)


class PulseAudioLoopback(LoopbackCapture):
    """Captures system audio on Linux via PulseAudio monitor devices.

    PulseAudio exposes "monitor" sources for each output sink, which
    provide loopback capture out of the box — no extra software needed.
    These appear as input devices with "Monitor" in their name.
    """

    def __init__(self, device_index: Optional[int] = None, sample_rate: Optional[int] = None) -> None:
        super().__init__(device_index=device_index, sample_rate=sample_rate)
        self._stream = None

    def _open_stream(self) -> None:
        device = self._device_index
        if device is None:
            device = self._find_monitor_device()

        dev_info = sd.query_devices(device)
        logger.info(
            "Opening PulseAudio monitor: device=%s  sr=%d",
            dev_info["name"], self._target_sr,
        )

        self._stream = sd.InputStream(
            samplerate=self._target_sr,
            channels=1,
            dtype="float32",
            device=device,
            blocksize=int(self._target_sr * 0.1),
            callback=self._stream_callback,
        )
        self._stream.start()
        logger.info("PulseAudio loopback capture started.")

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                logger.debug("Error closing PulseAudio stream", exc_info=True)
            self._stream = None
        logger.info("PulseAudio loopback capture stopped.")

    def _stream_callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            logger.debug("PulseAudio callback status: %s", status)
        mono = indata[:, 0].copy()
        self._push_audio(mono)

    @staticmethod
    def list_devices() -> list[dict]:
        """List PulseAudio monitor devices (loopback sources)."""
        devices = []
        all_devs = sd.query_devices()
        for i, dev in enumerate(all_devs):
            name = dev["name"]
            # PulseAudio monitor sources contain "Monitor" in name
            if dev["max_input_channels"] > 0 and "monitor" in name.lower():
                devices.append({
                    "index": i,
                    "name": name,
                    "is_loopback": True,
                    "channels": dev["max_input_channels"],
                    "default_sample_rate": int(dev["default_samplerate"]),
                })
        return devices

    @staticmethod
    def _find_monitor_device() -> int:
        """Find the default PulseAudio monitor device."""
        all_devs = sd.query_devices()
        for i, dev in enumerate(all_devs):
            if dev["max_input_channels"] > 0 and "monitor" in dev["name"].lower():
                logger.info("Auto-selected PulseAudio monitor: %s (idx=%d)", dev["name"], i)
                return i
        raise RuntimeError(
            "No PulseAudio monitor device found. "
            "Make sure PulseAudio is running and an audio output is active."
        )
