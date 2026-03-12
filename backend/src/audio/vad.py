"""Voice Activity Detection using Silero VAD."""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import torch

from src.utils.config import get_settings

logger = logging.getLogger(__name__)


class VoiceActivityDetector:
    """Wrapper around the Silero VAD model.

    Processes float32 mono audio at the configured sample rate and
    returns speech segment boundaries with their audio slices.
    """

    def __init__(
        self,
        threshold: float | None = None,
        min_speech_duration: float | None = None,
        min_silence_duration: float | None = None,
        sample_rate: int | None = None,
    ) -> None:
        settings = get_settings()

        self.threshold = threshold if threshold is not None else settings.vad_threshold
        self.min_speech_duration = (
            min_speech_duration
            if min_speech_duration is not None
            else settings.min_speech_duration
        )
        self.min_silence_duration = (
            min_silence_duration
            if min_silence_duration is not None
            else settings.min_silence_duration
        )
        self.sample_rate = sample_rate or settings.sample_rate

        # Silero VAD only supports 8000 and 16000 Hz.
        if self.sample_rate not in (8000, 16000):
            raise ValueError(
                f"Silero VAD only supports 8000 / 16000 Hz, got {self.sample_rate}"
            )

        logger.info("Loading Silero VAD model ...")
        self._model, self._utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
        )
        self._model.eval()
        logger.info("Silero VAD model loaded.")

        # Window size expected by Silero (in samples).
        # 512 for 16 kHz, 256 for 8 kHz.
        self._window_size = 512 if self.sample_rate == 16000 else 256

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, audio: np.ndarray) -> list[dict]:
        """Detect speech segments in *audio*.

        Parameters
        ----------
        audio : np.ndarray
            1-D float32 array at ``self.sample_rate``.

        Returns
        -------
        list[dict]
            Each dict contains:
            - ``start`` (float) — segment start in seconds
            - ``end``   (float) — segment end in seconds
            - ``audio`` (np.ndarray) — the corresponding audio slice
        """
        if len(audio) == 0:
            return []

        audio = audio.astype(np.float32)

        # Compute per-window speech probabilities.
        probs = self._get_speech_probabilities(audio)

        # Convert probabilities into segments.
        segments = self._probabilities_to_segments(probs, len(audio))

        # Attach audio slices.
        for seg in segments:
            start_sample = int(seg["start"] * self.sample_rate)
            end_sample = int(seg["end"] * self.sample_rate)
            seg["audio"] = audio[start_sample:end_sample]

        return segments

    def is_speech(self, audio: np.ndarray) -> bool:
        """Quick check whether *audio* contains speech.

        Runs the VAD on the full chunk and returns ``True`` if
        the mean probability exceeds the threshold.
        """
        if len(audio) == 0:
            return False

        probs = self._get_speech_probabilities(audio.astype(np.float32))
        if not probs:
            return False

        return float(np.mean(probs)) >= self.threshold

    def reset(self) -> None:
        """Reset the internal model state (hidden states / context)."""
        self._model.reset_states()
        logger.debug("VAD model state reset.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_speech_probabilities(self, audio: np.ndarray) -> list[float]:
        """Run the model on fixed-size windows and return probabilities."""
        self._model.reset_states()

        probs: list[float] = []
        n_samples = len(audio)
        window = self._window_size

        for offset in range(0, n_samples, window):
            chunk = audio[offset : offset + window]

            # Pad the last chunk if it's shorter than the window.
            if len(chunk) < window:
                chunk = np.pad(chunk, (0, window - len(chunk)), mode="constant")

            tensor = torch.from_numpy(chunk).float()
            prob = self._model(tensor, self.sample_rate).item()
            probs.append(prob)

        return probs

    def _probabilities_to_segments(
        self,
        probs: list[float],
        total_samples: int,
    ) -> list[dict]:
        """Convert per-window probabilities into merged speech segments.

        Applies ``min_speech_duration`` and ``min_silence_duration`` to
        filter and merge segments.
        """
        window_duration = self._window_size / self.sample_rate
        min_speech_windows = max(1, int(self.min_speech_duration / window_duration))
        min_silence_windows = max(1, int(self.min_silence_duration / window_duration))

        # Label each window as speech or silence.
        is_speech = [p >= self.threshold for p in probs]

        segments: list[dict] = []
        in_speech = False
        speech_start = 0
        silence_count = 0

        for i, speech in enumerate(is_speech):
            if speech:
                if not in_speech:
                    speech_start = i
                    in_speech = True
                silence_count = 0
            else:
                if in_speech:
                    silence_count += 1
                    if silence_count >= min_silence_windows:
                        # End of speech segment.
                        speech_end = i - silence_count + 1
                        duration_windows = speech_end - speech_start
                        if duration_windows >= min_speech_windows:
                            segments.append(
                                {
                                    "start": speech_start * window_duration,
                                    "end": min(
                                        speech_end * window_duration,
                                        total_samples / self.sample_rate,
                                    ),
                                }
                            )
                        in_speech = False
                        silence_count = 0

        # Handle segment that reaches the end of audio.
        if in_speech:
            speech_end = len(is_speech)
            duration_windows = speech_end - speech_start
            if duration_windows >= min_speech_windows:
                segments.append(
                    {
                        "start": speech_start * window_duration,
                        "end": min(
                            speech_end * window_duration,
                            total_samples / self.sample_rate,
                        ),
                    }
                )

        return segments
