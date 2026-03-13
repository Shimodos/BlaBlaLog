"""WASAPI Loopback capture for Windows using PyAudioWPatch."""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from src.audio.loopback.base import LoopbackCapture

logger = logging.getLogger(__name__)

try:
    import pyaudiowpatch as pyaudio
    _HAS_PYAUDIO = True
except ImportError:
    _HAS_PYAUDIO = False


class WasapiLoopback(LoopbackCapture):
    """Captures system audio via WASAPI loopback on Windows."""

    def __init__(self, device_index: Optional[int] = None, sample_rate: Optional[int] = None) -> None:
        super().__init__(device_index=device_index, sample_rate=sample_rate)
        if not _HAS_PYAUDIO:
            raise RuntimeError("PyAudioWPatch is required for Windows loopback capture. pip install PyAudioWPatch")
        self._pa = None
        self._stream = None
        self._src_sr: int = 0
        self._src_channels: int = 0

    def _open_stream(self) -> None:
        self._pa = pyaudio.PyAudio()
        device_info = self._resolve_device(self._pa, self._device_index)

        self._src_sr = int(device_info["defaultSampleRate"])
        self._src_channels = int(device_info["maxInputChannels"])
        device_idx = int(device_info["index"])

        logger.info(
            "Opening WASAPI loopback: device=%s  sr=%d  ch=%d",
            device_info["name"], self._src_sr, self._src_channels,
        )

        frames_per_buffer = int(self._src_sr * 0.1)

        self._stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=self._src_channels,
            rate=self._src_sr,
            input=True,
            input_device_index=device_idx,
            frames_per_buffer=frames_per_buffer,
            stream_callback=self._stream_callback,
        )
        self._stream.start_stream()
        logger.info("WASAPI loopback capture started.")

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                logger.debug("Error closing WASAPI stream", exc_info=True)
            self._stream = None

        if self._pa is not None:
            self._pa.terminate()
            self._pa = None
        logger.info("WASAPI loopback capture stopped.")

    def _stream_callback(self, in_data, frame_count, time_info, status):
        if status:
            logger.debug("WASAPI callback status: %s", status)
        raw = np.frombuffer(in_data, dtype=np.float32)
        mono = self._to_mono(raw, self._src_channels)
        resampled = self._resample(mono, self._src_sr, self._target_sr)
        self._push_audio(resampled)
        return (None, pyaudio.paContinue)

    @staticmethod
    def list_devices() -> list[dict]:
        if not _HAS_PYAUDIO:
            return []
        pa = pyaudio.PyAudio()
        devices = []
        try:
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if info.get("isLoopbackDevice", False) and info["maxInputChannels"] > 0:
                    devices.append({
                        "index": int(info["index"]),
                        "name": LoopbackCapture._fix_device_name(info["name"]),
                        "is_loopback": True,
                        "channels": int(info["maxInputChannels"]),
                        "default_sample_rate": int(info["defaultSampleRate"]),
                    })
        finally:
            pa.terminate()
        return devices

    @staticmethod
    def _resolve_device(pa, device_index: Optional[int]) -> dict:
        if device_index is not None:
            return pa.get_device_info_by_index(device_index)

        try:
            wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError:
            raise RuntimeError("WASAPI host API not available.")

        default_output_idx = wasapi_info["defaultOutputDevice"]
        default_output = pa.get_device_info_by_index(default_output_idx)
        default_name: str = default_output["name"]

        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("isLoopbackDevice", False) and info["maxInputChannels"] > 0 and default_name in info["name"]:
                return info

        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("isLoopbackDevice", False) and info["maxInputChannels"] > 0:
                return info

        raise RuntimeError("No WASAPI loopback device found.")
