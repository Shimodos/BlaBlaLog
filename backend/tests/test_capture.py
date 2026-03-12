"""Tests for audio capture (src.audio.capture).

All hardware and PyAudioWPatch interactions are mocked so the tests
run without actual audio devices.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helper: build a fake device info dict
# ---------------------------------------------------------------------------

def _fake_device(index: int, name: str, *, loopback: bool = False, channels: int = 2) -> dict:
    return {
        "index": index,
        "name": name,
        "isLoopbackDevice": loopback,
        "maxInputChannels": channels,
        "defaultSampleRate": 48000,
    }


FAKE_DEVICES = [
    _fake_device(0, "Speakers (Realtek)", loopback=False, channels=0),
    _fake_device(1, "Microphone (Realtek)", loopback=False, channels=2),
    _fake_device(2, "Speakers (Realtek) [Loopback]", loopback=True, channels=2),
    _fake_device(3, "HDMI Output [Loopback]", loopback=True, channels=2),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_pyaudio():
    """Patch ``pyaudiowpatch`` with a MagicMock and set up fake device info."""
    mock_pa_instance = MagicMock()
    mock_pa_instance.get_device_count.return_value = len(FAKE_DEVICES)
    mock_pa_instance.get_device_info_by_index.side_effect = lambda i: FAKE_DEVICES[i]

    mock_pa_class = MagicMock(return_value=mock_pa_instance)

    with patch.dict("sys.modules", {"pyaudiowpatch": MagicMock()}):
        import sys
        pa_mod = sys.modules["pyaudiowpatch"]
        pa_mod.PyAudio = mock_pa_class
        pa_mod.paFloat32 = 8  # numeric constant
        pa_mod.paContinue = 0
        pa_mod.paWASAPI = 13

        # Also patch get_settings so AudioCapture.__init__ works without env
        with patch("src.utils.config.get_settings") as mock_settings:
            settings = MagicMock()
            settings.sample_rate = 16000
            mock_settings.return_value = settings

            # Need to reload capture to pick up the mocked pyaudiowpatch
            import importlib
            import src.audio.capture as capture_mod
            importlib.reload(capture_mod)

            yield {
                "pa_class": mock_pa_class,
                "pa_instance": mock_pa_instance,
                "capture_mod": capture_mod,
                "AudioCapture": capture_mod.AudioCapture,
            }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestListDevices:
    def test_list_devices_returns_list_of_dicts(self, mock_pyaudio):
        AudioCapture = mock_pyaudio["AudioCapture"]
        devices = AudioCapture.list_devices()

        assert isinstance(devices, list)
        assert len(devices) == len(FAKE_DEVICES)

        expected_keys = {"index", "name", "is_loopback", "channels", "default_sample_rate"}
        for d in devices:
            assert isinstance(d, dict)
            assert set(d.keys()) == expected_keys

    def test_list_devices_values(self, mock_pyaudio):
        AudioCapture = mock_pyaudio["AudioCapture"]
        devices = AudioCapture.list_devices()

        loopback_dev = devices[2]
        assert loopback_dev["index"] == 2
        assert loopback_dev["is_loopback"] is True
        assert loopback_dev["channels"] == 2
        assert loopback_dev["default_sample_rate"] == 48000


class TestListLoopbackDevices:
    def test_filters_to_loopback_only(self, mock_pyaudio):
        AudioCapture = mock_pyaudio["AudioCapture"]
        loopbacks = AudioCapture.list_loopback_devices()

        assert len(loopbacks) == 2
        assert all(d["is_loopback"] for d in loopbacks)

    def test_loopback_names(self, mock_pyaudio):
        AudioCapture = mock_pyaudio["AudioCapture"]
        loopbacks = AudioCapture.list_loopback_devices()
        names = [d["name"] for d in loopbacks]
        assert "Speakers (Realtek) [Loopback]" in names
        assert "HDMI Output [Loopback]" in names


class TestCaptureContextManager:
    def test_enter_exit(self, mock_pyaudio):
        AudioCapture = mock_pyaudio["AudioCapture"]
        pa_instance = mock_pyaudio["pa_instance"]

        # Configure _resolve_device to work
        wasapi_info = {"defaultOutputDevice": 0}
        pa_instance.get_host_api_info_by_type.return_value = wasapi_info
        # Make get_device_info_by_index return a loopback for the search
        pa_instance.get_device_info_by_index.side_effect = lambda i: FAKE_DEVICES[i]

        mock_stream = MagicMock()
        pa_instance.open.return_value = mock_stream

        capture = AudioCapture(device_index=2)

        result = capture.__enter__()
        assert result is capture
        assert capture.is_recording is True

        capture.__exit__(None, None, None)
        assert capture.is_recording is False
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()


class TestCaptureStartStop:
    def test_start_opens_stream_and_sets_recording(self, mock_pyaudio):
        AudioCapture = mock_pyaudio["AudioCapture"]
        pa_instance = mock_pyaudio["pa_instance"]

        mock_stream = MagicMock()
        pa_instance.open.return_value = mock_stream

        capture = AudioCapture(device_index=2)
        assert capture.is_recording is False

        capture.start()
        assert capture.is_recording is True
        pa_instance.open.assert_called_once()
        mock_stream.start_stream.assert_called_once()

    def test_stop_closes_stream_and_terminates(self, mock_pyaudio):
        AudioCapture = mock_pyaudio["AudioCapture"]
        pa_instance = mock_pyaudio["pa_instance"]

        mock_stream = MagicMock()
        pa_instance.open.return_value = mock_stream

        capture = AudioCapture(device_index=2)
        capture.start()
        capture.stop()

        assert capture.is_recording is False
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()
        pa_instance.terminate.assert_called()

    def test_start_when_already_recording_is_noop(self, mock_pyaudio):
        AudioCapture = mock_pyaudio["AudioCapture"]
        pa_instance = mock_pyaudio["pa_instance"]

        mock_stream = MagicMock()
        pa_instance.open.return_value = mock_stream

        capture = AudioCapture(device_index=2)
        capture.start()
        capture.start()  # second call should be a no-op

        # open should have been called only once
        assert pa_instance.open.call_count == 1

    def test_stop_when_not_recording_is_noop(self, mock_pyaudio):
        AudioCapture = mock_pyaudio["AudioCapture"]
        capture = AudioCapture(device_index=2)
        # Should not raise
        capture.stop()
        assert capture.is_recording is False

    def test_sample_rate_property(self, mock_pyaudio):
        AudioCapture = mock_pyaudio["AudioCapture"]
        capture = AudioCapture(device_index=2, sample_rate=44100)
        assert capture.sample_rate == 44100
