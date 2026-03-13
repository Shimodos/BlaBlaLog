"""CoreAudio loopback capture for macOS via BlackHole/Soundflower virtual device."""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import sounddevice as sd

from src.audio.loopback.base import LoopbackCapture

logger = logging.getLogger(__name__)

# Known virtual audio device names for macOS loopback
_VIRTUAL_DEVICES = ["blackhole", "soundflower", "loopback"]


class CoreAudioLoopback(LoopbackCapture):
    """Captures system audio on macOS via a virtual audio device.

    macOS does not natively support loopback capture. Users must install
    a virtual audio driver like BlackHole (free) or Loopback (paid).
    The virtual device acts as a bridge: system audio is routed to it,
    and this class reads from it like a normal input device.

    Setup (one-time):
    1. Install BlackHole: brew install blackhole-2ch
    2. Create a Multi-Output Device in Audio MIDI Setup:
       - Include your speakers + BlackHole 2ch
    3. Set the Multi-Output as default output
    4. VoiceScribe will auto-detect BlackHole as loopback source
    """

    def __init__(self, device_index: Optional[int] = None, sample_rate: Optional[int] = None) -> None:
        super().__init__(device_index=device_index, sample_rate=sample_rate)
        self._stream = None

    def _open_stream(self) -> None:
        device = self._device_index
        if device is None:
            device = self._find_virtual_device()

        dev_info = sd.query_devices(device)
        logger.info(
            "Opening CoreAudio virtual device: device=%s  sr=%d",
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
        logger.info("CoreAudio loopback capture started.")

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                logger.debug("Error closing CoreAudio stream", exc_info=True)
            self._stream = None
        logger.info("CoreAudio loopback capture stopped.")

    def _stream_callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            logger.debug("CoreAudio callback status: %s", status)
        mono = indata[:, 0].copy()
        self._push_audio(mono)

    @staticmethod
    def list_devices() -> list[dict]:
        """List virtual audio devices that can serve as loopback sources."""
        devices = []
        all_devs = sd.query_devices()
        for i, dev in enumerate(all_devs):
            name_lower = dev["name"].lower()
            if dev["max_input_channels"] > 0 and any(vd in name_lower for vd in _VIRTUAL_DEVICES):
                devices.append({
                    "index": i,
                    "name": dev["name"],
                    "is_loopback": True,
                    "channels": dev["max_input_channels"],
                    "default_sample_rate": int(dev["default_samplerate"]),
                })
        return devices

    @staticmethod
    def _find_virtual_device() -> int:
        """Auto-detect a virtual audio device for loopback."""
        all_devs = sd.query_devices()
        for i, dev in enumerate(all_devs):
            name_lower = dev["name"].lower()
            if dev["max_input_channels"] > 0 and any(vd in name_lower for vd in _VIRTUAL_DEVICES):
                logger.info("Auto-selected virtual device: %s (idx=%d)", dev["name"], i)
                return i
        raise RuntimeError(
            "No virtual audio device found for loopback capture on macOS.\n"
            "Please install BlackHole: brew install blackhole-2ch\n"
            "Then create a Multi-Output Device in Audio MIDI Setup."
        )
