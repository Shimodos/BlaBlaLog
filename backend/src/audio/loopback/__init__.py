"""Platform-aware loopback (system audio) capture.

Usage:
    from src.audio.loopback import get_loopback_capture
    capture = get_loopback_capture(device_index=None)
    capture.start()
    audio = capture.get_audio(30)  # last 30 seconds
    capture.stop()
"""

from __future__ import annotations

import sys
import logging
from typing import Optional

from src.audio.loopback.base import LoopbackCapture

logger = logging.getLogger(__name__)


def get_loopback_capture(
    device_index: Optional[int] = None,
    sample_rate: Optional[int] = None,
) -> LoopbackCapture:
    """Factory: return the correct LoopbackCapture for the current platform."""

    if sys.platform == "win32":
        from src.audio.loopback.wasapi import WasapiLoopback
        return WasapiLoopback(device_index=device_index, sample_rate=sample_rate)

    elif sys.platform == "darwin":
        from src.audio.loopback.coreaudio import CoreAudioLoopback
        return CoreAudioLoopback(device_index=device_index, sample_rate=sample_rate)

    elif sys.platform.startswith("linux"):
        from src.audio.loopback.pulseaudio import PulseAudioLoopback
        return PulseAudioLoopback(device_index=device_index, sample_rate=sample_rate)

    else:
        raise RuntimeError(f"Unsupported platform for loopback capture: {sys.platform}")


def list_loopback_devices() -> list[dict]:
    """List available loopback devices for the current platform."""

    if sys.platform == "win32":
        from src.audio.loopback.wasapi import WasapiLoopback
        return WasapiLoopback.list_devices()

    elif sys.platform == "darwin":
        from src.audio.loopback.coreaudio import CoreAudioLoopback
        return CoreAudioLoopback.list_devices()

    elif sys.platform.startswith("linux"):
        from src.audio.loopback.pulseaudio import PulseAudioLoopback
        return PulseAudioLoopback.list_devices()

    return []
