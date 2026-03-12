"""SpeechBrain ECAPA-TDNN voice embeddings for speaker identification."""

from __future__ import annotations

from pathlib import Path
from typing import Union

import numpy as np

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Embedding dimensionality produced by ECAPA-TDNN (VoxCeleb).
EMBEDDING_DIM = 192


class VoiceEmbedder:
    """Extract and compare speaker voice embeddings using ECAPA-TDNN."""

    def __init__(self) -> None:
        self._available = False
        self._model = None

        try:
            from speechbrain.inference.speaker import EncoderClassifier  # type: ignore[import-untyped]

            self._model = EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                savedir="pretrained_models/spkrec-ecapa-voxceleb",
                run_opts={"device": "cpu"},
            )
            self._available = True
            logger.info("ECAPA-TDNN voice embedder loaded successfully")
        except Exception as exc:  # noqa: BLE001
            logger.warning("SpeechBrain ECAPA-TDNN unavailable: %s", exc)
            self._available = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Whether the ECAPA-TDNN model is loaded and ready."""
        return self._available

    def extract(self, audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        """Extract a 192-dim voice embedding from a raw audio waveform.

        Args:
            audio: 1-D float32 numpy array of audio samples.
            sample_rate: Sampling rate of *audio* (default 16 kHz).

        Returns:
            A 1-D numpy array of shape ``(192,)`` with the speaker embedding.

        Raises:
            RuntimeError: If the model is not available.
        """
        if not self._available:
            raise RuntimeError("ECAPA-TDNN model is not available")

        import torch  # type: ignore[import-untyped]

        # Ensure float32, mono, 1-D
        if audio.ndim > 1:
            audio = audio.mean(axis=-1)

        waveform = torch.tensor(audio, dtype=torch.float32).unsqueeze(0)

        # Resample if needed
        if sample_rate != 16000:
            try:
                import torchaudio  # type: ignore[import-untyped]

                waveform = torchaudio.functional.resample(
                    waveform, orig_freq=sample_rate, new_freq=16000
                )
            except ImportError:
                logger.warning(
                    "torchaudio not installed; cannot resample from %d Hz", sample_rate
                )

        embedding = self._model.encode_batch(waveform)
        # encode_batch returns shape (1, 1, 192) — squeeze to (192,)
        return embedding.squeeze().cpu().numpy().astype(np.float32)

    def extract_from_file(self, audio_path: Union[str, Path]) -> np.ndarray:
        """Load an audio file and extract a voice embedding.

        Args:
            audio_path: Path to a WAV (or compatible) audio file.

        Returns:
            A 1-D numpy array of shape ``(192,)`` with the speaker embedding.
        """
        if not self._available:
            raise RuntimeError("ECAPA-TDNN model is not available")

        audio_path = Path(audio_path)

        # Try torchaudio first, fall back to soundfile
        try:
            import torchaudio  # type: ignore[import-untyped]

            waveform, sr = torchaudio.load(str(audio_path))
            audio = waveform.squeeze(0).numpy()
        except Exception:  # noqa: BLE001
            import soundfile as sf  # type: ignore[import-untyped]

            audio, sr = sf.read(str(audio_path), dtype="float32")

        return self.extract(audio, sample_rate=sr)

    @staticmethod
    def compare(embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        """Compute cosine similarity between two embeddings.

        Args:
            embedding1: First speaker embedding (1-D array).
            embedding2: Second speaker embedding (1-D array).

        Returns:
            Cosine similarity in the range ``[0.0, 1.0]``.
        """
        norm1 = np.linalg.norm(embedding1)
        norm2 = np.linalg.norm(embedding2)

        if norm1 == 0.0 or norm2 == 0.0:
            return 0.0

        similarity = float(np.dot(embedding1, embedding2) / (norm1 * norm2))
        # Clamp to [0, 1] — negative cosine means very different speakers.
        return max(0.0, min(1.0, similarity))
