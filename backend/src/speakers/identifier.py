"""Real-time speaker identification against known voice profiles."""

from __future__ import annotations

from typing import Optional

import numpy as np

from src.speakers.embeddings import VoiceEmbedder
from src.speakers.profiles import SpeakerProfileManager
from src.storage.models import Speaker
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SpeakerIdentifier:
    """Identify speakers by comparing voice embeddings to stored profiles."""

    def __init__(
        self,
        profile_manager: SpeakerProfileManager,
        threshold: Optional[float] = None,
    ) -> None:
        self.profile_manager = profile_manager
        self.threshold = threshold if threshold is not None else get_settings().speaker_threshold
        self._embedder: VoiceEmbedder = profile_manager.embedder

        # Lazy-loaded cache: list of (Speaker, embedding).
        self._profiles_cache: list[tuple[Speaker, np.ndarray]] = []
        self._cache_loaded = False

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    async def load_profiles(self) -> None:
        """Refresh the in-memory profile cache from the database."""
        self._profiles_cache = await self.profile_manager.get_all_profiles()
        self._cache_loaded = True
        logger.info("Loaded %d speaker profiles into cache", len(self._profiles_cache))

    async def _ensure_cache(self) -> None:
        """Load the cache on first use."""
        if not self._cache_loaded:
            await self.load_profiles()

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------

    async def identify(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
    ) -> tuple[Optional[str], str, float]:
        """Identify a speaker from an audio chunk.

        Args:
            audio: 1-D float32 numpy waveform.
            sample_rate: Sampling rate of *audio*.

        Returns:
            A tuple ``(speaker_id, speaker_name, confidence)``.
            If no profile exceeds the threshold the speaker_id is ``None``
            and the name is ``"Unknown"``.
        """
        await self._ensure_cache()

        if not self._profiles_cache:
            return (None, "Unknown", 0.0)

        embedding = self._embedder.extract(audio, sample_rate=sample_rate)

        best_id: Optional[str] = None
        best_name: str = "Unknown"
        best_score: float = 0.0

        for speaker, profile_emb in self._profiles_cache:
            score = VoiceEmbedder.compare(embedding, profile_emb)
            if score > best_score:
                best_score = score
                best_id = speaker.id
                best_name = speaker.name

        if best_score >= self.threshold:
            logger.debug(
                "Identified speaker '%s' (confidence=%.3f)", best_name, best_score
            )
            return (best_id, best_name, best_score)

        logger.debug("No speaker matched above threshold (best=%.3f)", best_score)
        return (None, "Unknown", best_score)

    async def identify_segments(
        self,
        diarization_segments: list[dict],
        full_audio: np.ndarray,
        sample_rate: int = 16000,
    ) -> dict[str, tuple[Optional[str], str]]:
        """Identify speakers for each unique diarization label.

        Each diarization segment dict must have at least::

            {"speaker": "SPEAKER_00", "start": float_seconds, "end": float_seconds}

        Audio belonging to each unique speaker label is concatenated and a
        single embedding is extracted, then compared against stored profiles.

        Args:
            diarization_segments: List of segment dicts from the diarizer.
            full_audio: 1-D float32 numpy waveform of the complete recording.
            sample_rate: Sampling rate of *full_audio*.

        Returns:
            Mapping ``{"SPEAKER_00": (speaker_id_or_None, "John"), ...}``.
        """
        await self._ensure_cache()

        # Group audio slices by speaker label.
        speaker_audio: dict[str, list[np.ndarray]] = {}
        for seg in diarization_segments:
            label = seg["speaker"]
            start_sample = int(seg["start"] * sample_rate)
            end_sample = int(seg["end"] * sample_rate)
            # Clamp to valid range
            start_sample = max(0, start_sample)
            end_sample = min(len(full_audio), end_sample)
            if end_sample <= start_sample:
                continue
            chunk = full_audio[start_sample:end_sample]
            speaker_audio.setdefault(label, []).append(chunk)

        result: dict[str, tuple[Optional[str], str]] = {}

        for label, chunks in speaker_audio.items():
            concatenated = np.concatenate(chunks)

            # Need a minimum amount of audio to get a reliable embedding.
            min_samples = int(0.5 * sample_rate)  # 0.5 seconds
            if len(concatenated) < min_samples:
                logger.warning(
                    "Speaker '%s' has only %.2fs of audio; marking as Unknown",
                    label,
                    len(concatenated) / sample_rate,
                )
                result[label] = (None, "Unknown")
                continue

            speaker_id, name, confidence = await self.identify(
                concatenated, sample_rate=sample_rate
            )
            result[label] = (speaker_id, name)
            logger.info(
                "Diarization label '%s' -> '%s' (confidence=%.3f)",
                label,
                name,
                confidence,
            )

        # Handle labels with no audio at all.
        all_labels = {seg["speaker"] for seg in diarization_segments}
        for label in all_labels - result.keys():
            result[label] = (None, "Unknown")

        return result
