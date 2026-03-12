"""JSON-RPC 2.0 over stdio handler for Tauri <-> Python sidecar communication."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import sys
import time
import uuid
import wave
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np

from src.storage.database import Database
from src.storage.export import TranscriptExporter
from src.storage.models import Meeting, Segment, Speaker
from src.utils.config import get_settings
from src.utils.logger import get_logger

# Lazy imports for heavy modules (torch-dependent)
AudioCapture = None
MicrophoneCapture = None
VoiceActivityDetector = None
SpeakerDiarizer = None
VoiceEmbedder = None
SpeakerIdentifier = None
SpeakerProfileManager = None
TranscriptionEngine = None
StreamingTranscriber = None


def _lazy_import_audio():
    global AudioCapture, MicrophoneCapture
    if AudioCapture is None:
        from src.audio.capture import AudioCapture as _AC
        AudioCapture = _AC
    try:
        if MicrophoneCapture is None:
            from src.audio.microphone import MicrophoneCapture as _MC
            MicrophoneCapture = _MC
    except ImportError:
        pass


def _lazy_import_ml():
    global VoiceActivityDetector, TranscriptionEngine, StreamingTranscriber
    global SpeakerDiarizer, VoiceEmbedder, SpeakerIdentifier, SpeakerProfileManager
    try:
        if VoiceActivityDetector is None:
            from src.audio.vad import VoiceActivityDetector as _VAD
            VoiceActivityDetector = _VAD
        if TranscriptionEngine is None:
            from src.transcription.engine import TranscriptionEngine as _TE
            TranscriptionEngine = _TE
        if StreamingTranscriber is None:
            from src.transcription.streaming import StreamingTranscriber as _ST
            StreamingTranscriber = _ST
    except ImportError as e:
        get_logger(__name__).warning(f"ML modules not available: {e}")
    try:
        if SpeakerDiarizer is None:
            from src.speakers.diarization import SpeakerDiarizer as _SD
            SpeakerDiarizer = _SD
        if VoiceEmbedder is None:
            from src.speakers.embeddings import VoiceEmbedder as _VE
            VoiceEmbedder = _VE
        if SpeakerIdentifier is None:
            from src.speakers.identifier import SpeakerIdentifier as _SI
            SpeakerIdentifier = _SI
        if SpeakerProfileManager is None:
            from src.speakers.profiles import SpeakerProfileManager as _SPM
            SpeakerProfileManager = _SPM
    except ImportError as e:
        get_logger(__name__).warning(f"Speaker modules not available: {e}")

logger = get_logger(__name__)

# JSON-RPC 2.0 standard error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class JsonRpcHandler:
    """Reads JSON-RPC 2.0 requests from stdin, dispatches to methods, writes responses to stdout.

    Designed to run as a Tauri sidecar process, communicating over newline-delimited JSON.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._db = Database(self._settings.db_path)
        self._capture: Optional[AudioCapture] = None
        self._mic_capture: Optional[MicrophoneCapture] = None
        self._recording_start: Optional[float] = None
        self._current_meeting_id: Optional[str] = None
        self._running = False

        # Streaming transcription components (initialized lazily on first recording)
        self._engine: Optional[TranscriptionEngine] = None
        self._vad: Optional[VoiceActivityDetector] = None
        self._streamer: Optional[StreamingTranscriber] = None
        self._audio_feed_task: Optional[asyncio.Task] = None

        # Speaker analysis components (initialized with graceful fallback)
        self._embedder: Optional[VoiceEmbedder] = None
        self._diarizer: Optional[SpeakerDiarizer] = None
        self._profile_manager: Optional[SpeakerProfileManager] = None
        self._identifier: Optional[SpeakerIdentifier] = None

        # Method dispatch table
        self._methods: dict[str, Any] = {
            "ping": self._handle_ping,
            "get_devices": self._handle_get_devices,
            "get_loopback_devices": self._handle_get_loopback_devices,
            "get_input_devices": self._handle_get_input_devices,
            "get_output_devices": self._handle_get_output_devices,
            "start_recording": self._handle_start_recording,
            "stop_recording": self._handle_stop_recording,
            "get_status": self._handle_get_status,
            "list_meetings": self._handle_list_meetings,
            "get_meeting": self._handle_get_meeting,
            "delete_meeting": self._handle_delete_meeting,
            "get_transcript": self._handle_get_transcript,
            "export": self._handle_export,
            "list_speakers": self._handle_list_speakers,
            "create_speaker_profile": self._handle_create_speaker_profile,
            "train_speaker_from_segment": self._handle_train_speaker_from_segment,
            "delete_speaker": self._handle_delete_speaker,
            "get_settings": self._handle_get_settings,
            "update_settings": self._handle_update_settings,
            "update_meeting": self._handle_update_meeting,
            "start_speaker_recording": self._handle_start_speaker_recording,
            "stop_speaker_recording": self._handle_stop_speaker_recording,
        }

    # ------------------------------------------------------------------
    # Initialization of ML components
    # ------------------------------------------------------------------

    def _init_transcription_engine(self) -> TranscriptionEngine:
        """Lazily initialize the Whisper transcription engine."""
        if self._engine is None:
            self._engine = TranscriptionEngine(
                model_size=self._settings.whisper_model,
                device=self._settings.whisper_device,
                language=self._settings.language,
            )
        return self._engine

    def _init_vad(self) -> VoiceActivityDetector:
        """Lazily initialize the VAD model."""
        if self._vad is None:
            self._vad = VoiceActivityDetector()
        return self._vad

    def _init_speaker_components(self) -> None:
        """Initialize speaker diarization, embedding, and identification components.

        All failures are caught gracefully — the handler continues to work
        without speaker features if models cannot be loaded.
        """
        # Voice embedder
        try:
            self._embedder = VoiceEmbedder()
            if not self._embedder.available:
                logger.warning("VoiceEmbedder loaded but model not available.")
                self._embedder = None
        except Exception:
            logger.warning("Failed to initialize VoiceEmbedder", exc_info=True)
            self._embedder = None

        # Speaker diarizer
        try:
            self._diarizer = SpeakerDiarizer()
            if not self._diarizer.available:
                logger.warning("SpeakerDiarizer loaded but pipeline not available.")
                self._diarizer = None
        except Exception:
            logger.warning("Failed to initialize SpeakerDiarizer", exc_info=True)
            self._diarizer = None

        # Profile manager and identifier require the embedder
        if self._embedder is not None:
            self._profile_manager = SpeakerProfileManager(
                database=self._db, embedder=self._embedder
            )
            self._identifier = SpeakerIdentifier(
                profile_manager=self._profile_manager,
                threshold=self._settings.speaker_threshold,
            )
        else:
            logger.warning(
                "Speaker profile management and identification disabled "
                "(VoiceEmbedder not available)."
            )

    # ------------------------------------------------------------------
    # Main event loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start the handler: initialize DB, then read stdin line by line."""
        # Force UTF-8 on Windows stdio to handle Cyrillic and other non-ASCII text
        if sys.platform == "win32":
            import io as _io
            sys.stdin = _io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
            sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

        # Lazy-load heavy modules (torch, ML models)
        _lazy_import_audio()
        _lazy_import_ml()

        await self._db.init()
        self._running = True

        # Initialize speaker components in the background (may take time to load models).
        await asyncio.to_thread(self._init_speaker_components)

        logger.info("JSON-RPC handler started, waiting for requests on stdin.")

        # Use thread-based stdin reading (Windows ProactorEventLoop doesn't support connect_read_pipe)
        loop = asyncio.get_event_loop()

        while self._running:
            try:
                line_str = await loop.run_in_executor(None, self._read_stdin_line)
                if line_str is None:
                    logger.info("stdin closed, shutting down.")
                    break

                line_str = line_str.strip()
                if not line_str:
                    continue

                await self._process_line(line_str)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Unexpected error in main loop")

        await self._shutdown()

    @staticmethod
    def _read_stdin_line() -> str | None:
        """Blocking read of one line from stdin. Returns None on EOF."""
        try:
            line = sys.stdin.readline()
            if not line:
                return None
            return line
        except (EOFError, OSError):
            return None

    async def _shutdown(self) -> None:
        """Clean up resources on exit."""
        self._running = False

        # Cancel the audio feed task if running.
        if self._audio_feed_task and not self._audio_feed_task.done():
            self._audio_feed_task.cancel()
            try:
                await self._audio_feed_task
            except asyncio.CancelledError:
                pass
            self._audio_feed_task = None

        # Stop streaming transcriber.
        if self._streamer and self._streamer.is_running:
            await self._streamer.stop()
            self._streamer = None

        # Stop audio captures.
        if self._capture and self._capture.is_recording:
            self._capture.stop()
            self._capture = None
        if self._mic_capture and self._mic_capture.is_recording:
            self._mic_capture.stop()
            self._mic_capture = None

        await self._db.close()
        logger.info("JSON-RPC handler shut down.")

    # ------------------------------------------------------------------
    # Request processing
    # ------------------------------------------------------------------

    async def _process_line(self, line: str) -> None:
        """Parse a single JSON-RPC request line and dispatch it."""
        # Parse JSON
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            self._write_error(None, PARSE_ERROR, f"Parse error: {exc}")
            return

        # Validate basic structure
        if not isinstance(request, dict):
            self._write_error(None, INVALID_REQUEST, "Request must be a JSON object")
            return

        jsonrpc = request.get("jsonrpc")
        if jsonrpc != "2.0":
            self._write_error(
                request.get("id"), INVALID_REQUEST, "Missing or invalid 'jsonrpc' field"
            )
            return

        method = request.get("method")
        if not isinstance(method, str):
            self._write_error(
                request.get("id"), INVALID_REQUEST, "Missing or invalid 'method' field"
            )
            return

        params = request.get("params", {})
        if not isinstance(params, dict):
            params = {}

        request_id = request.get("id")  # None for notifications

        # Dispatch
        handler = self._methods.get(method)
        if handler is None:
            if request_id is not None:
                self._write_error(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")
            return

        try:
            result = await handler(params)
            if request_id is not None:
                self._write_result(request_id, result)
        except TypeError as exc:
            if request_id is not None:
                self._write_error(request_id, INVALID_PARAMS, f"Invalid params: {exc}")
        except Exception as exc:
            logger.exception("Error handling method '%s'", method)
            if request_id is not None:
                self._write_error(request_id, INTERNAL_ERROR, str(exc))

    # ------------------------------------------------------------------
    # Response writing
    # ------------------------------------------------------------------

    def _write_result(self, request_id: Any, result: Any) -> None:
        """Write a success response to stdout."""
        response = {"jsonrpc": "2.0", "result": result, "id": request_id}
        self._write_json(response)

    def _write_error(self, request_id: Any, code: int, message: str) -> None:
        """Write an error response to stdout."""
        response = {
            "jsonrpc": "2.0",
            "error": {"code": code, "message": message},
            "id": request_id,
        }
        self._write_json(response)

    def send_notification(self, method: str, params: Any = None) -> None:
        """Send a JSON-RPC notification (no id) to the frontend.

        Use this for streaming events like partial transcripts.
        """
        notification: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            notification["params"] = params
        self._write_json(notification)

    def _write_json(self, obj: dict) -> None:
        """Serialize and write a JSON object as a single line to stdout."""
        line = json.dumps(obj, ensure_ascii=False, default=str)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    # ------------------------------------------------------------------
    # Audio feed loop for streaming transcription
    # ------------------------------------------------------------------

    async def _audio_feed_loop(self) -> None:
        """Background task that reads audio chunks from capture and feeds them
        to the StreamingTranscriber for real-time transcription.

        Runs until the capture is stopped or the task is cancelled.
        """
        chunk_seconds = 2.0
        logger.info("Audio feed loop started (chunk=%.1fs)", chunk_seconds)

        try:
            while self._capture and self._capture.is_recording and self._streamer and self._streamer.is_running:
                # Read the next chunk in a thread (blocking call).
                chunk = await asyncio.to_thread(
                    self._capture.read_chunk, chunk_seconds
                )

                if chunk.size == 0:
                    # Capture was stopped while we were waiting.
                    break

                # Feed to the streaming transcriber.
                await self._streamer.feed(chunk)
        except asyncio.CancelledError:
            logger.info("Audio feed loop cancelled.")
            raise
        except Exception:
            logger.exception("Error in audio feed loop")
        finally:
            logger.info("Audio feed loop ended.")

    # ------------------------------------------------------------------
    # Streaming transcription callbacks
    # ------------------------------------------------------------------

    async def _on_partial_transcript(self, text: str, start: float) -> None:
        """Called by StreamingTranscriber with interim (partial) text."""
        self.send_notification("transcript.partial", {
            "meeting_id": self._current_meeting_id,
            "text": text,
            "start": start,
        })

    async def _on_final_segment(self, segment: dict) -> None:
        """Called by StreamingTranscriber when a segment is finalized."""
        meeting_id = self._current_meeting_id
        if not meeting_id:
            return

        # Persist the segment to the database.
        db_segment = Segment(
            meeting_id=meeting_id,
            speaker_id=None,
            speaker_label="Unknown",
            start_time=segment["start"],
            end_time=segment["end"],
            text=segment["text"],
            confidence=segment.get("confidence"),
        )
        segment_id = await self._db.add_segment(db_segment)

        # Notify the frontend.
        self.send_notification("transcript.final", {
            "meeting_id": meeting_id,
            "segment_id": segment_id,
            "text": segment["text"],
            "start": segment["start"],
            "end": segment["end"],
            "confidence": segment.get("confidence"),
            "speaker_label": "Unknown",
        })

    # ------------------------------------------------------------------
    # Method handlers
    # ------------------------------------------------------------------

    async def _handle_ping(self, params: dict) -> str:
        return "pong"

    async def _handle_get_devices(self, params: dict) -> list[dict]:
        return await asyncio.to_thread(AudioCapture.list_devices)

    async def _handle_get_loopback_devices(self, params: dict) -> list[dict]:
        return await asyncio.to_thread(AudioCapture.list_loopback_devices)

    async def _handle_get_input_devices(self, params: dict) -> list[dict]:
        """List available microphone input devices."""
        return await asyncio.to_thread(MicrophoneCapture.list_devices)

    async def _handle_get_output_devices(self, params: dict) -> list[dict]:
        """List available system/loopback output devices."""
        return await asyncio.to_thread(AudioCapture.list_loopback_devices)

    async def _handle_start_recording(self, params: dict) -> dict:
        """Start recording audio (mic + loopback). Transcription happens on stop.

        Params:
            loopback_device_index (int, optional): WASAPI loopback device index.
            mic_device_index (int, optional): Microphone input device index.
        """
        if self._capture and self._capture.is_recording:
            raise RuntimeError("Already recording. Stop the current recording first.")

        loopback_index = params.get("loopback_device_index") or params.get("device_index")
        mic_index = params.get("mic_device_index")

        # Create a new meeting record
        meeting_id = str(uuid.uuid4())
        now = datetime.utcnow()
        meeting = Meeting(
            id=meeting_id,
            started_at=now,
            created_at=now,
            language=self._settings.language,
        )
        await self._db.create_meeting(meeting)
        self._current_meeting_id = meeting_id

        # Start loopback capture (system audio)
        if loopback_index is not None:
            self._capture = AudioCapture(device_index=loopback_index)
        else:
            self._capture = AudioCapture()  # auto-detect default loopback
        await asyncio.to_thread(self._capture.start)

        # Start microphone capture (if available and requested)
        if MicrophoneCapture is not None:
            try:
                self._mic_capture = MicrophoneCapture(device_index=mic_index)
                await asyncio.to_thread(self._mic_capture.start)
                logger.info("Microphone capture started (device_index=%s)", mic_index)
            except Exception:
                logger.warning("Failed to start microphone capture", exc_info=True)
                self._mic_capture = None

        self._recording_start = time.monotonic()

        # Start VU meter task to send audio level updates to frontend
        self._audio_feed_task = asyncio.create_task(self._vu_meter_loop())

        logger.info("Recording started (record-then-transcribe), meeting_id=%s", meeting_id)
        return {"meeting_id": meeting_id, "status": "recording"}

    async def _vu_meter_loop(self) -> None:
        """Send audio level (RMS) updates to the frontend every 200ms."""
        try:
            while self._capture and self._capture.is_recording:
                levels: dict[str, float] = {}

                # Loopback level
                if self._capture and self._capture.is_recording:
                    chunk = self._capture.get_audio(0.2)
                    if chunk.size > 0:
                        rms = float(np.sqrt(np.mean(chunk ** 2)))
                        levels["loopback"] = min(1.0, rms * 10)  # normalize to 0-1

                # Mic level
                if self._mic_capture and self._mic_capture.is_recording:
                    chunk = self._mic_capture.get_audio(0.2)
                    if chunk.size > 0:
                        rms = float(np.sqrt(np.mean(chunk ** 2)))
                        levels["mic"] = min(1.0, rms * 10)

                if levels:
                    self.send_notification("audio.levels", levels)

                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error in VU meter loop")

    async def _handle_stop_recording(self, params: dict) -> dict:
        """Stop recording and run batch transcription + diarization + speaker ID.

        The heavy processing runs in background; progress is sent via notifications.
        Returns immediately with meeting_id and duration.
        """
        if not self._capture or not self._capture.is_recording:
            raise RuntimeError("Not currently recording.")

        meeting_id = self._current_meeting_id

        # 1. Cancel VU meter task.
        if self._audio_feed_task and not self._audio_feed_task.done():
            self._audio_feed_task.cancel()
            try:
                await self._audio_feed_task
            except asyncio.CancelledError:
                pass
            self._audio_feed_task = None

        # 2. Get the full recorded audio from both sources.
        loopback_audio = await asyncio.to_thread(self._capture.get_audio, 7200.0)
        sample_rate = self._capture.sample_rate

        mic_audio = np.array([], dtype=np.float32)
        if self._mic_capture and self._mic_capture.is_recording:
            mic_audio = await asyncio.to_thread(self._mic_capture.get_audio, 7200.0)

        # 3. Stop captures.
        await asyncio.to_thread(self._capture.stop)
        if self._mic_capture and self._mic_capture.is_recording:
            await asyncio.to_thread(self._mic_capture.stop)

        # 4. Create mixed audio for WAV save, keep separate for transcription.
        if loopback_audio.size > 0 and mic_audio.size > 0:
            # Pad shorter to match longer
            max_len = max(len(loopback_audio), len(mic_audio))
            if len(loopback_audio) < max_len:
                loopback_audio = np.pad(loopback_audio, (0, max_len - len(loopback_audio)))
            if len(mic_audio) < max_len:
                mic_audio = np.pad(mic_audio, (0, max_len - len(mic_audio)))
            full_audio = (loopback_audio * 0.5 + mic_audio * 0.5).astype(np.float32)
        elif loopback_audio.size > 0:
            full_audio = loopback_audio
        else:
            full_audio = mic_audio

        has_dual_audio = loopback_audio.size > 0 and mic_audio.size > 0

        # Calculate duration
        duration = 0
        if self._recording_start is not None:
            duration = int(time.monotonic() - self._recording_start)

        # 5. Save mixed audio to WAV.
        audio_path = None
        if meeting_id and full_audio.size > 0:
            save_dir = Path(self._settings.audio_save_path)
            save_dir.mkdir(parents=True, exist_ok=True)
            audio_path = str(save_dir / f"{meeting_id}.wav")
            await asyncio.to_thread(
                self._save_audio_wav, full_audio, sample_rate, audio_path
            )

        # Update meeting record.
        if meeting_id:
            await self._db.update_meeting(
                meeting_id,
                ended_at=datetime.utcnow(),
                duration_seconds=duration,
                audio_path=audio_path,
            )

        # Send immediate response, then process in background.
        result: dict[str, Any] = {
            "meeting_id": meeting_id,
            "duration_seconds": duration,
            "status": "processing",
        }

        # 6. Launch batch processing as background task.
        # Pass separate audio streams for source-based speaker identification.
        asyncio.create_task(
            self._batch_process(
                meeting_id, full_audio, sample_rate, duration,
                mic_audio=mic_audio if has_dual_audio else None,
                loopback_audio=loopback_audio if has_dual_audio else None,
            )
        )

        # Clean up recording state (not ML state — that's reused).
        self._capture = None
        self._mic_capture = None
        self._recording_start = None

        logger.info("Recording stopped, meeting_id=%s, duration=%ds, starting batch processing", meeting_id, duration)
        return result

    def _cluster_speakers(
        self,
        segments: list[dict],
        full_audio: np.ndarray,
        sample_rate: int,
        similarity_threshold: float = 0.75,
    ) -> list[str]:
        """Cluster segments by speaker using ECAPA-TDNN embeddings.

        Extracts an embedding for each segment's audio slice, then
        greedily assigns segments to speaker clusters based on cosine
        similarity.  Returns a list of speaker labels aligned with *segments*.
        """
        embeddings: list[np.ndarray] = []
        valid_indices: list[int] = []

        for i, seg in enumerate(segments):
            start_sample = int(seg["start"] * sample_rate)
            end_sample = int(seg["end"] * sample_rate)
            chunk = full_audio[start_sample:end_sample]

            # Skip very short chunks (< 0.5s) — not enough audio for embedding
            if len(chunk) < sample_rate * 0.5:
                embeddings.append(np.zeros(192, dtype=np.float32))
                continue

            try:
                emb = self._embedder.extract(chunk, sample_rate)
                embeddings.append(emb)
                valid_indices.append(i)
            except Exception:
                embeddings.append(np.zeros(192, dtype=np.float32))

        if not valid_indices:
            return [f"Speaker 1" for _ in segments]

        # Greedy clustering: assign each segment to nearest existing cluster
        # or create a new cluster if similarity is below threshold
        clusters: list[list[int]] = []  # cluster_id -> list of segment indices
        centroids: list[np.ndarray] = []  # cluster_id -> mean embedding

        for i in valid_indices:
            emb = embeddings[i]
            best_cluster = -1
            best_sim = 0.0

            for c_idx, centroid in enumerate(centroids):
                sim = float(np.dot(emb, centroid) / (
                    np.linalg.norm(emb) * np.linalg.norm(centroid) + 1e-8
                ))
                if sim > best_sim:
                    best_sim = sim
                    best_cluster = c_idx

            if best_sim >= similarity_threshold and best_cluster >= 0:
                clusters[best_cluster].append(i)
                # Update centroid (running mean)
                cluster_embs = [embeddings[j] for j in clusters[best_cluster]]
                centroids[best_cluster] = np.mean(cluster_embs, axis=0)
            else:
                clusters.append([i])
                centroids.append(emb.copy())

        # Build label map
        seg_to_label: dict[int, str] = {}
        for c_idx, members in enumerate(clusters):
            label = f"Speaker {c_idx + 1}"
            for seg_idx in members:
                seg_to_label[seg_idx] = label

        # Assign labels — segments without valid embeddings get nearest neighbor's label
        labels: list[str] = []
        for i in range(len(segments)):
            if i in seg_to_label:
                labels.append(seg_to_label[i])
            elif labels:
                labels.append(labels[-1])  # inherit from previous segment
            else:
                labels.append("Speaker 1")

        logger.info(
            "Speaker clustering: %d clusters from %d segments (threshold=%.2f)",
            len(clusters), len(segments), similarity_threshold,
        )
        return labels

    async def _batch_process(
        self,
        meeting_id: str,
        full_audio: np.ndarray,
        sample_rate: int,
        duration: int,
        *,
        mic_audio: Optional[np.ndarray] = None,
        loopback_audio: Optional[np.ndarray] = None,
    ) -> None:
        """Background: batch transcribe → identify speakers → merge → save.

        If mic_audio and loopback_audio are provided (dual-source mode),
        each stream is transcribed separately and labelled by source:
        mic → "You (Mic)", loopback → "Remote (System)".
        Otherwise falls back to single-source with embedding-based clustering.
        """
        try:
            audio_minutes = round(duration / 60, 1)
            engine = await asyncio.to_thread(self._init_transcription_engine)

            dual_mode = mic_audio is not None and loopback_audio is not None
            is_multilingual = self._settings.language == "auto"

            # Pick transcription method: multilingual (per-chunk auto-detect) or fixed language
            def _transcribe(audio_data: np.ndarray) -> list[dict]:
                if is_multilingual:
                    return engine.transcribe_multilingual(audio_data, beam_size=1, vad_filter=True)
                return engine.transcribe(audio_data, None, 1, True)

            if dual_mode:
                # ===== DUAL-SOURCE MODE =====
                # Transcribe mic and loopback separately → assign speaker by source
                self.send_notification("processing.status", {
                    "meeting_id": meeting_id,
                    "stage": "transcription",
                    "progress": 0,
                    "message": f"Transcribing microphone ({audio_minutes} min)...",
                })

                mic_segments = await asyncio.to_thread(_transcribe, mic_audio)
                logger.info("Mic transcription: %d segments", len(mic_segments))

                self.send_notification("processing.status", {
                    "meeting_id": meeting_id,
                    "stage": "transcription",
                    "progress": 50,
                    "message": f"Transcribing system audio ({audio_minutes} min)...",
                })

                loopback_segments = await asyncio.to_thread(_transcribe, loopback_audio)
                logger.info("Loopback transcription: %d segments", len(loopback_segments))

                # Tag segments by source
                all_segments: list[dict] = []
                for seg in mic_segments:
                    s = dict(seg)
                    s["speaker_label"] = "You (Mic)"
                    all_segments.append(s)
                for seg in loopback_segments:
                    s = dict(seg)
                    s["speaker_label"] = "Remote (System)"
                    all_segments.append(s)

                # Sort by start time (interleave mic + loopback chronologically)
                all_segments.sort(key=lambda s: s["start"])

            else:
                # ===== SINGLE-SOURCE MODE =====
                self.send_notification("processing.status", {
                    "meeting_id": meeting_id,
                    "stage": "transcription",
                    "progress": 0,
                    "message": f"Transcribing {audio_minutes} min of audio...",
                })

                raw_segments = await asyncio.to_thread(_transcribe, full_audio)
                logger.info("Batch transcription: %d raw segments", len(raw_segments))

                # Try embedding-based speaker clustering
                speaker_labels: list[str] = ["Speaker" for _ in raw_segments]
                if self._embedder and self._embedder.available and len(raw_segments) > 1:
                    self.send_notification("processing.status", {
                        "meeting_id": meeting_id,
                        "stage": "identification",
                        "progress": 0,
                        "message": "Identifying speakers...",
                    })
                    try:
                        speaker_labels = await asyncio.to_thread(
                            self._cluster_speakers, raw_segments, full_audio, sample_rate
                        )
                        logger.info("Speaker clustering: %d speakers", len(set(speaker_labels)))
                    except Exception:
                        logger.exception("Speaker clustering failed")

                all_segments = []
                for seg, label in zip(raw_segments, speaker_labels):
                    s = dict(seg)
                    s["speaker_label"] = label
                    all_segments.append(s)

            # --- Transcription done ---
            self.send_notification("processing.status", {
                "meeting_id": meeting_id,
                "stage": "transcription",
                "progress": 100,
                "message": f"Transcription complete: {len(all_segments)} segments",
            })

            # --- Merge adjacent segments from SAME speaker (gap < 3s) ---
            merged: list[dict] = []
            max_gap = 3.0
            for seg in all_segments:
                label = seg.get("speaker_label", "Speaker")
                if (
                    merged
                    and merged[-1]["speaker_label"] == label
                    and seg["start"] - merged[-1]["end"] < max_gap
                ):
                    merged[-1]["end"] = seg["end"]
                    merged[-1]["text"] = merged[-1]["text"].rstrip() + " " + seg["text"].lstrip()
                    prev_conf = merged[-1].get("confidence") or 1.0
                    cur_conf = seg.get("confidence") or 1.0
                    merged[-1]["confidence"] = min(prev_conf, cur_conf)
                else:
                    merged.append(dict(seg))

            logger.info("After merging: %d segments (from %d)", len(merged), len(all_segments))

            # Save merged segments to DB
            for seg in merged:
                db_segment = Segment(
                    meeting_id=meeting_id,
                    speaker_id=None,
                    speaker_label=seg.get("speaker_label", "Speaker"),
                    start_time=seg["start"],
                    end_time=seg["end"],
                    text=seg["text"],
                    confidence=seg.get("confidence"),
                )
                await self._db.add_segment(db_segment)

            # --- Done ---
            final_segments = await self._db.get_segments(meeting_id)
            self.send_notification("processing.status", {
                "meeting_id": meeting_id,
                "stage": "complete",
                "progress": 100,
                "message": f"Done! {len(final_segments)} segments, {len({s.speaker_label for s in final_segments})} speakers.",
                "segments": [
                    {
                        "id": s.id,
                        "speaker_id": s.speaker_id,
                        "speaker_label": s.speaker_label,
                        "start_time": s.start_time,
                        "end_time": s.end_time,
                        "text": s.text,
                        "confidence": s.confidence,
                    }
                    for s in final_segments
                ],
            })

            self._current_meeting_id = None

        except Exception:
            logger.exception("Batch processing failed for meeting %s", meeting_id)
            self.send_notification("processing.status", {
                "meeting_id": meeting_id,
                "stage": "error",
                "progress": 0,
                "message": "Processing failed. Check logs for details.",
            })
            self._current_meeting_id = None

    async def _handle_get_status(self, params: dict) -> dict:
        is_recording = bool(self._capture and self._capture.is_recording)
        duration = 0.0
        if is_recording and self._recording_start is not None:
            duration = round(time.monotonic() - self._recording_start, 1)

        return {
            "state": "recording" if is_recording else "idle",
            "meeting_id": self._current_meeting_id,
            "duration_seconds": duration,
            "has_diarizer": self._diarizer is not None and self._diarizer.available,
            "has_identifier": self._identifier is not None,
        }

    async def _handle_list_meetings(self, params: dict) -> list[dict]:
        limit = params.get("limit", 50)
        offset = params.get("offset", 0)
        meetings = await self._db.list_meetings(limit=limit, offset=offset)
        return [
            {
                "id": m.id,
                "title": m.title,
                "started_at": str(m.started_at),
                "ended_at": str(m.ended_at) if m.ended_at else None,
                "duration_seconds": m.duration_seconds,
                "language": m.language,
            }
            for m in meetings
        ]

    async def _handle_get_meeting(self, params: dict) -> dict:
        meeting_id = params.get("meeting_id")
        if not meeting_id:
            raise TypeError("Missing required param: meeting_id")

        meeting = await self._db.get_meeting(meeting_id)
        if meeting is None:
            raise ValueError(f"Meeting not found: {meeting_id}")

        return {
            "id": meeting.id,
            "title": meeting.title,
            "started_at": str(meeting.started_at),
            "ended_at": str(meeting.ended_at) if meeting.ended_at else None,
            "duration_seconds": meeting.duration_seconds,
            "audio_path": meeting.audio_path,
            "language": meeting.language,
            "created_at": str(meeting.created_at),
        }

    async def _handle_delete_meeting(self, params: dict) -> dict:
        """Delete a meeting and its segments + audio file."""
        meeting_id = params.get("meeting_id")
        if not meeting_id:
            raise TypeError("Missing required param: meeting_id")

        # Delete audio file if exists
        meeting = await self._db.get_meeting(meeting_id)
        if meeting and meeting.audio_path:
            try:
                audio_file = Path(meeting.audio_path)
                if audio_file.exists():
                    audio_file.unlink()
                    logger.info("Deleted audio file: %s", meeting.audio_path)
            except Exception:
                logger.warning("Failed to delete audio file: %s", meeting.audio_path, exc_info=True)

        # Delete segments first (foreign key), then meeting
        await self._db._db.execute("DELETE FROM segments WHERE meeting_id = ?", (meeting_id,))
        await self._db.delete_meeting(meeting_id)
        logger.info("Deleted meeting: %s", meeting_id)

        return {"deleted": True, "meeting_id": meeting_id}

    async def _handle_get_transcript(self, params: dict) -> list[dict]:
        meeting_id = params.get("meeting_id")
        if not meeting_id:
            raise TypeError("Missing required param: meeting_id")

        segments = await self._db.get_segments(meeting_id)
        return [
            {
                "id": s.id,
                "speaker_id": s.speaker_id,
                "speaker_label": s.speaker_label,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "text": s.text,
                "confidence": s.confidence,
            }
            for s in segments
        ]

    async def _handle_export(self, params: dict) -> dict:
        meeting_id = params.get("meeting_id")
        fmt = params.get("format")
        path = params.get("path")

        if not meeting_id:
            raise TypeError("Missing required param: meeting_id")
        if not fmt:
            raise TypeError("Missing required param: format")
        if not path:
            raise TypeError("Missing required param: path")

        meeting = await self._db.get_meeting(meeting_id)
        if meeting is None:
            raise ValueError(f"Meeting not found: {meeting_id}")

        segments = await self._db.get_segments(meeting_id)
        exporter = TranscriptExporter(segments=segments, meeting=meeting)
        exporter.save(Path(path), format=fmt)

        logger.info("Exported meeting %s to %s (format=%s)", meeting_id, path, fmt)
        return {"path": path, "format": fmt}

    async def _handle_list_speakers(self, params: dict) -> list[dict]:
        speakers = await self._db.list_speakers()
        return [
            {
                "id": s.id,
                "name": s.name,
                "sample_audio_path": s.sample_audio_path,
                "created_at": str(s.created_at),
                "has_embedding": s.embedding is not None and len(s.embedding) > 0,
            }
            for s in speakers
        ]

    async def _handle_create_speaker_profile(self, params: dict) -> dict:
        """Create a new speaker profile.

        Params:
            name (str): Speaker name.
            audio_base64 (str, optional): Base64-encoded WAV audio.
                If not provided, uses the last speaker training recording.
        """
        name = params.get("name")
        audio_base64 = params.get("audio_base64")

        if not name:
            raise TypeError("Missing required param: name")

        # Get audio from base64 or from last training recording
        audio: Optional[np.ndarray] = None
        sample_rate = 16000

        if audio_base64:
            audio_bytes = base64.b64decode(audio_base64)
            audio, sample_rate = self._decode_wav_bytes(audio_bytes)
        elif hasattr(self, '_speaker_training_audio') and self._speaker_training_audio is not None:
            audio = self._speaker_training_audio
            sample_rate = self._speaker_training_sr

        if self._profile_manager is not None and audio is not None and len(audio) > 0:
            speaker = await self._profile_manager.create_profile(
                name=name,
                audio=audio,
                sample_rate=sample_rate,
            )
            if self._identifier:
                await self._identifier.load_profiles()
            logger.info("Created speaker profile '%s' with embedding (id=%s)", name, speaker.id)
        else:
            # Create profile without embedding (name only)
            speaker = Speaker(name=name)
            await self._db.add_speaker(speaker)
            logger.info("Created speaker profile '%s' (name only, id=%s)", name, speaker.id)

        # Clear training audio
        self._speaker_training_audio = None
        self._speaker_training_sr = 16000

        return {
            "id": speaker.id,
            "name": speaker.name,
            "created_at": str(speaker.created_at),
        }

    async def _handle_train_speaker_from_segment(self, params: dict) -> dict:
        """Create or update a speaker profile from a segment of a meeting recording.

        Params:
            name (str): Speaker name.
            meeting_id (str): Meeting to extract audio from.
            start_time (float): Start time in seconds.
            end_time (float): End time in seconds.
        """
        name = params.get("name")
        meeting_id = params.get("meeting_id")
        start_time = params.get("start_time")
        end_time = params.get("end_time")

        if not name:
            raise TypeError("Missing required param: name")
        if not meeting_id:
            raise TypeError("Missing required param: meeting_id")
        if start_time is None or end_time is None:
            raise TypeError("Missing required params: start_time, end_time")
        if self._profile_manager is None:
            raise RuntimeError(
                "Speaker profile management is not available. "
                "Voice embedding model could not be loaded."
            )

        # Load the meeting's audio file.
        meeting = await self._db.get_meeting(meeting_id)
        if meeting is None:
            raise ValueError(f"Meeting not found: {meeting_id}")
        if not meeting.audio_path:
            raise ValueError(f"Meeting {meeting_id} has no saved audio file.")

        audio_path = Path(meeting.audio_path)
        if not audio_path.is_file():
            raise ValueError(f"Audio file not found: {audio_path}")

        # Load audio and extract the requested segment.
        full_audio, sample_rate = await asyncio.to_thread(
            self._load_wav_file, str(audio_path)
        )

        start_sample = int(start_time * sample_rate)
        end_sample = int(end_time * sample_rate)
        start_sample = max(0, start_sample)
        end_sample = min(len(full_audio), end_sample)

        if end_sample <= start_sample:
            raise ValueError("Invalid time range: start_time must be less than end_time")

        segment_audio = full_audio[start_sample:end_sample]

        # Create the speaker profile.
        speaker = await self._profile_manager.create_profile(
            name=name,
            audio=segment_audio,
            sample_rate=sample_rate,
        )

        # Refresh the identifier cache.
        if self._identifier:
            await self._identifier.load_profiles()

        logger.info(
            "Created speaker profile '%s' from meeting %s [%.1f-%.1f]s",
            name, meeting_id, start_time, end_time,
        )
        return {
            "id": speaker.id,
            "name": speaker.name,
            "created_at": str(speaker.created_at),
        }

    async def _handle_delete_speaker(self, params: dict) -> dict:
        """Delete a speaker profile.

        Params:
            speaker_id (str): UUID of the speaker to delete.
        """
        speaker_id = params.get("speaker_id")
        if not speaker_id:
            raise TypeError("Missing required param: speaker_id")

        if self._profile_manager is None:
            # Fall back to direct DB deletion if profile manager is unavailable.
            await self._db.delete_speaker(speaker_id)
        else:
            await self._profile_manager.delete_profile(speaker_id)

        # Refresh the identifier cache.
        if self._identifier:
            await self._identifier.load_profiles()

        logger.info("Deleted speaker profile id=%s", speaker_id)
        return {"speaker_id": speaker_id, "deleted": True}

    async def _handle_get_settings(self, params: dict) -> dict:
        """Return current application settings."""
        s = self._settings
        return {
            "whisper_model": s.whisper_model,
            "whisper_device": s.whisper_device,
            "language": s.language,
            "sample_rate": s.sample_rate,
            "vad_threshold": s.vad_threshold,
            "min_speech_duration": s.min_speech_duration,
            "min_silence_duration": s.min_silence_duration,
            "speaker_threshold": s.speaker_threshold,
            "log_level": s.log_level,
            "db_path": str(s.db_path),
            "audio_save_path": str(s.audio_save_path),
        }

    async def _handle_update_meeting(self, params: dict) -> dict:
        """Update meeting metadata (title, etc.)."""
        meeting_id = params.get("meeting_id")
        if not meeting_id:
            raise TypeError("Missing required param: meeting_id")

        title = params.get("title")
        if title is not None:
            await self._db._db.execute(
                "UPDATE meetings SET title = ? WHERE id = ?",
                (title, meeting_id),
            )
            await self._db._db.commit()
            logger.info("Meeting %s title updated to: %s", meeting_id, title)

        return {"meeting_id": meeting_id, "updated": True}

    async def _handle_start_speaker_recording(self, params: dict) -> dict:
        """Start a short voice recording for speaker profile training."""
        # Use microphone to record a voice sample
        _lazy_import_audio()
        mic_index = params.get("device_index")

        if MicrophoneCapture is None:
            raise RuntimeError("MicrophoneCapture is not available")

        # Store in a temporary capture for speaker training
        self._speaker_training_capture = MicrophoneCapture(device_index=mic_index)
        await asyncio.to_thread(self._speaker_training_capture.start)
        logger.info("Speaker training recording started")
        return {"status": "recording"}

    async def _handle_stop_speaker_recording(self, params: dict) -> dict:
        """Stop speaker voice recording and return audio data."""
        if not hasattr(self, '_speaker_training_capture') or self._speaker_training_capture is None:
            raise RuntimeError("No speaker training recording in progress")

        audio = await asyncio.to_thread(self._speaker_training_capture.get_audio, 60.0)
        await asyncio.to_thread(self._speaker_training_capture.stop)
        sample_rate = self._speaker_training_capture.sample_rate
        self._speaker_training_capture = None

        # Save for create_speaker_profile to use
        self._speaker_training_audio = audio
        self._speaker_training_sr = sample_rate

        duration = len(audio) / sample_rate if sample_rate > 0 else 0
        logger.info("Speaker training recording stopped: %.1fs", duration)

        return {"status": "success", "duration": round(duration, 1)}

    async def _handle_update_settings(self, params: dict) -> dict:
        """Update a single setting value.

        Params:
            key (str): Setting name (e.g. "language", "speaker_threshold").
            value (any): New value for the setting.

        Note: Some settings (like whisper_model) require a restart to take
        effect. Runtime-changeable settings are applied immediately.
        """
        key = params.get("key")
        value = params.get("value")

        if not key:
            raise TypeError("Missing required param: key")
        if value is None:
            raise TypeError("Missing required param: value")

        # Validate that the key exists in Settings.
        if not hasattr(self._settings, key):
            raise ValueError(f"Unknown setting: {key}")

        # Update the in-memory settings object.
        # Note: pydantic-settings doesn't support direct mutation by default,
        # so we update via __dict__ for runtime changes.
        current_type = type(getattr(self._settings, key))
        try:
            typed_value = current_type(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid value for '{key}': {exc}")

        object.__setattr__(self._settings, key, typed_value)

        # Apply runtime-sensitive changes immediately.
        if key == "speaker_threshold" and self._identifier:
            self._identifier.threshold = typed_value
        elif key == "language" and self._engine:
            self._engine._language = typed_value

        logger.info("Setting '%s' updated to %r", key, typed_value)
        return {"key": key, "value": typed_value, "applied": True}

    # ------------------------------------------------------------------
    # Audio utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_wav_bytes(wav_bytes: bytes) -> tuple[np.ndarray, int]:
        """Decode WAV bytes into a float32 numpy array and sample rate."""
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            sample_rate = wf.getframerate()
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)

        if sampwidth == 2:
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        elif sampwidth == 4:
            audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            # Fallback: treat as raw float32.
            audio = np.frombuffer(raw, dtype=np.float32)

        # Convert to mono if multi-channel.
        if n_channels > 1:
            audio = audio.reshape(-1, n_channels).mean(axis=1).astype(np.float32)

        return audio, sample_rate

    @staticmethod
    def _load_wav_file(path: str) -> tuple[np.ndarray, int]:
        """Load a WAV file and return (float32_audio, sample_rate)."""
        with wave.open(path, "rb") as wf:
            sample_rate = wf.getframerate()
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)

        if sampwidth == 2:
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        elif sampwidth == 4:
            audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            audio = np.frombuffer(raw, dtype=np.float32)

        if n_channels > 1:
            audio = audio.reshape(-1, n_channels).mean(axis=1).astype(np.float32)

        return audio, sample_rate

    @staticmethod
    def _save_audio_wav(audio: np.ndarray, sample_rate: int, path: str) -> None:
        """Save a float32 numpy audio array to a WAV file."""
        pcm = np.clip(audio, -1.0, 1.0)
        pcm = (pcm * 32767).astype(np.int16)

        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm.tobytes())


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------


def main() -> None:
    """Launch the JSON-RPC handler as a standalone process."""
    handler = JsonRpcHandler()
    try:
        asyncio.run(handler.run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")


if __name__ == "__main__":
    main()
