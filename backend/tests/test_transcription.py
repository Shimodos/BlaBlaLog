"""Tests for transcription engine (src.transcription.engine).

faster_whisper.WhisperModel is fully mocked so no ML model is needed.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_whisper():
    """Patch faster_whisper.WhisperModel and return the mock + engine."""
    mock_model_instance = MagicMock()

    with patch.dict("sys.modules", {
        "faster_whisper": MagicMock(),
        "faster_whisper.audio": MagicMock(),
        "faster_whisper.transcribe": MagicMock(),
    }):
        import sys
        fw = sys.modules["faster_whisper"]
        mock_model_cls = MagicMock(return_value=mock_model_instance)
        fw.WhisperModel = mock_model_cls

        # Patch torch away so _resolve_device falls back to cpu
        with patch.dict("sys.modules", {"torch": None}):
            import importlib
            import src.transcription.engine as engine_mod
            importlib.reload(engine_mod)

            engine = engine_mod.TranscriptionEngine(
                model_size="tiny",
                device="cpu",
                language="en",
            )

            yield {
                "engine": engine,
                "model_instance": mock_model_instance,
                "engine_mod": engine_mod,
            }


def _make_fake_segment(text: str, start: float, end: float, avg_logprob: float = -0.3):
    """Create a fake segment object mimicking faster-whisper output."""
    return SimpleNamespace(
        text=text,
        start=start,
        end=end,
        avg_logprob=avg_logprob,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEngineInit:
    def test_properties(self, mock_whisper):
        engine = mock_whisper["engine"]
        assert engine.model_size == "tiny"
        assert engine.device == "cpu"
        assert engine.language == "en"


class TestTranscribeEmptyAudio:
    def test_empty_array_returns_empty_list(self, mock_whisper):
        engine = mock_whisper["engine"]
        result = engine.transcribe(np.array([], dtype=np.float32))
        assert result == []

    def test_short_audio_returns_empty_list(self, mock_whisper):
        engine = mock_whisper["engine"]
        # Less than _MIN_AUDIO_SAMPLES (400)
        short = np.zeros(100, dtype=np.float32)
        result = engine.transcribe(short)
        assert result == []

    def test_none_audio_returns_empty_list(self, mock_whisper):
        engine = mock_whisper["engine"]
        result = engine.transcribe(None)
        assert result == []


class TestTranscribeReturnsSegments:
    def test_output_format(self, mock_whisper):
        engine = mock_whisper["engine"]
        model = mock_whisper["model_instance"]

        fake_segments = [
            _make_fake_segment(" Hello world ", 0.0, 2.5, -0.2),
            _make_fake_segment(" How are you? ", 2.5, 5.0, -0.4),
        ]
        fake_info = SimpleNamespace(language="en", language_probability=0.98)
        model.transcribe.return_value = (iter(fake_segments), fake_info)

        audio = np.random.randn(16000 * 5).astype(np.float32)
        result = engine.transcribe(audio, language="en")

        assert isinstance(result, list)
        assert len(result) == 2

        for seg in result:
            assert "text" in seg
            assert "start" in seg
            assert "end" in seg
            assert "confidence" in seg
            assert isinstance(seg["text"], str)
            assert isinstance(seg["start"], float)
            assert isinstance(seg["end"], float)
            assert isinstance(seg["confidence"], float)
            assert 0.0 <= seg["confidence"] <= 1.0

    def test_text_is_stripped(self, mock_whisper):
        engine = mock_whisper["engine"]
        model = mock_whisper["model_instance"]

        fake_segments = [_make_fake_segment("  padded text  ", 0.0, 1.0)]
        fake_info = SimpleNamespace(language="en", language_probability=0.98)
        model.transcribe.return_value = (iter(fake_segments), fake_info)

        audio = np.random.randn(16000).astype(np.float32)
        result = engine.transcribe(audio)

        assert result[0]["text"] == "padded text"

    def test_timestamps_are_rounded(self, mock_whisper):
        engine = mock_whisper["engine"]
        model = mock_whisper["model_instance"]

        fake_segments = [_make_fake_segment("test", 1.23456, 2.78901)]
        fake_info = SimpleNamespace(language="en", language_probability=0.98)
        model.transcribe.return_value = (iter(fake_segments), fake_info)

        audio = np.random.randn(16000 * 3).astype(np.float32)
        result = engine.transcribe(audio)

        assert result[0]["start"] == 1.235
        assert result[0]["end"] == 2.789


class TestDetectLanguage:
    def test_detect_returns_tuple(self, mock_whisper):
        engine = mock_whisper["engine"]
        model = mock_whisper["model_instance"]

        fake_info = SimpleNamespace(language="ru", language_probability=0.9512)
        model.transcribe.return_value = (iter([_make_fake_segment("тест", 0, 1)]), fake_info)

        audio = np.random.randn(16000).astype(np.float32)
        lang, prob = engine.detect_language(audio)

        assert lang == "ru"
        assert isinstance(prob, float)
        assert 0.0 <= prob <= 1.0

    def test_detect_raises_on_empty_audio(self, mock_whisper):
        engine = mock_whisper["engine"]
        with pytest.raises(ValueError, match="too short"):
            engine.detect_language(np.array([], dtype=np.float32))

    def test_detect_calls_transcribe_without_language(self, mock_whisper):
        engine = mock_whisper["engine"]
        model = mock_whisper["model_instance"]

        fake_info = SimpleNamespace(language="en", language_probability=0.99)
        model.transcribe.return_value = (iter([_make_fake_segment("hi", 0, 1)]), fake_info)

        audio = np.random.randn(16000).astype(np.float32)
        engine.detect_language(audio)

        # Verify language=None was passed to force auto-detection
        call_kwargs = model.transcribe.call_args
        assert call_kwargs[1]["language"] is None
