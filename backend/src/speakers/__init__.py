"""Speaker identification subsystem."""

from src.speakers.embeddings import VoiceEmbedder
from src.speakers.identifier import SpeakerIdentifier
from src.speakers.profiles import SpeakerProfileManager

__all__ = ["VoiceEmbedder", "SpeakerIdentifier", "SpeakerProfileManager"]
