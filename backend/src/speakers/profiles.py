"""Speaker profile management — create, update, delete, list."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import numpy as np

from src.speakers.embeddings import EMBEDDING_DIM, VoiceEmbedder
from src.storage.database import Database
from src.storage.models import Speaker
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SpeakerProfileManager:
    """CRUD operations for speaker voice profiles backed by the database."""

    def __init__(self, database: Database, embedder: VoiceEmbedder) -> None:
        self.database = database
        self.embedder = embedder

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_profile(
        self,
        name: str,
        audio: np.ndarray,
        sample_rate: int = 16000,
        sample_audio_path: Optional[str] = None,
    ) -> Speaker:
        """Create a new speaker profile from an audio sample.

        Args:
            name: Human-readable name for the speaker.
            audio: 1-D float32 numpy audio waveform.
            sample_rate: Sampling rate of *audio*.
            sample_audio_path: Optional path where the reference audio is stored.

        Returns:
            The newly created :class:`Speaker` model.
        """
        embedding = self.embedder.extract(audio, sample_rate=sample_rate)
        embedding_bytes = self.serialize_embedding(embedding)

        speaker = Speaker(
            id=str(uuid.uuid4()),
            name=name,
            embedding=embedding_bytes,
            sample_audio_path=sample_audio_path,
            created_at=datetime.utcnow(),
        )

        await self.database.create_speaker(speaker)
        logger.info("Created speaker profile '%s' (id=%s)", name, speaker.id)
        return speaker

    async def update_profile(
        self,
        speaker_id: str,
        audio: np.ndarray,
        sample_rate: int = 16000,
    ) -> None:
        """Update an existing speaker profile by averaging a new audio sample.

        The new embedding is averaged with the existing one so the profile
        becomes more robust over time.

        Args:
            speaker_id: UUID of the speaker to update.
            audio: 1-D float32 numpy audio waveform with new voice sample.
            sample_rate: Sampling rate of *audio*.
        """
        speaker = await self.database.get_speaker(speaker_id)
        if speaker is None:
            raise ValueError(f"Speaker {speaker_id} not found")

        new_embedding = self.embedder.extract(audio, sample_rate=sample_rate)
        old_embedding = self.deserialize_embedding(speaker.embedding)

        # Running average of old and new embeddings.
        averaged = (old_embedding + new_embedding) / 2.0
        # Re-normalise so cosine similarity stays well-scaled.
        norm = np.linalg.norm(averaged)
        if norm > 0:
            averaged = averaged / norm

        await self.database.update_speaker(
            speaker_id, embedding=self.serialize_embedding(averaged)
        )
        logger.info("Updated embedding for speaker '%s' (id=%s)", speaker.name, speaker_id)

    async def delete_profile(self, speaker_id: str) -> None:
        """Delete a speaker profile from the database."""
        await self.database.delete_speaker(speaker_id)
        logger.info("Deleted speaker profile id=%s", speaker_id)

    async def get_all_profiles(self) -> list[tuple[Speaker, np.ndarray]]:
        """Load every speaker and deserialize their embeddings.

        Returns:
            List of ``(Speaker, embedding_array)`` tuples.
        """
        speakers = await self.database.list_speakers()
        results: list[tuple[Speaker, np.ndarray]] = []
        for sp in speakers:
            try:
                emb = self.deserialize_embedding(sp.embedding)
                results.append((sp, emb))
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to deserialize embedding for speaker '%s' (id=%s); skipping",
                    sp.name,
                    sp.id,
                )
        return results

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def serialize_embedding(embedding: np.ndarray) -> bytes:
        """Convert a numpy embedding to raw bytes for database storage."""
        return embedding.astype(np.float32).tobytes()

    @staticmethod
    def deserialize_embedding(data: bytes) -> np.ndarray:
        """Reconstruct a numpy embedding from raw bytes."""
        return np.frombuffer(data, dtype=np.float32).copy()
