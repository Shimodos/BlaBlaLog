import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


def _get_user_data_dir() -> Path:
    """Return a stable, user-writable directory for all VoiceScribe data.

    Windows: %APPDATA%/VoiceScribe
    macOS:   ~/Library/Application Support/VoiceScribe
    Linux:   ~/.local/share/VoiceScribe
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "VoiceScribe"


USER_DATA_DIR = _get_user_data_dir()


class Settings(BaseSettings):
    whisper_model: str = "base"  # base=fast on CPU, small=better quality, tiny=instant
    whisper_device: str = "auto"
    language: str = "auto"
    sample_rate: int = 16000
    vad_threshold: float = 0.5
    min_speech_duration: float = 0.5
    min_silence_duration: float = 0.3
    db_path: Path = USER_DATA_DIR / "voicescribe.db"
    audio_save_path: Path = USER_DATA_DIR / "recordings"
    speakers_audio_path: Path = USER_DATA_DIR / "speakers"
    log_level: str = "INFO"
    speaker_threshold: float = 0.70

    model_config = {
        "env_prefix": "VOICESCRIBE_",
    }


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Ensure data directories exist
    s.db_path.parent.mkdir(parents=True, exist_ok=True)
    s.audio_save_path.mkdir(parents=True, exist_ok=True)
    s.speakers_audio_path.mkdir(parents=True, exist_ok=True)
    return s
