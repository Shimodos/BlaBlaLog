from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    whisper_model: str = "small"
    whisper_device: str = "auto"
    language: str = "ru"
    sample_rate: int = 16000
    vad_threshold: float = 0.5
    min_speech_duration: float = 0.5
    min_silence_duration: float = 0.3
    db_path: Path = Path("data/voicescribe.db")
    audio_save_path: Path = Path("data/recordings")
    speaker_threshold: float = 0.70
    log_level: str = "INFO"

    model_config = {
        "env_prefix": "VOICESCRIBE_",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
