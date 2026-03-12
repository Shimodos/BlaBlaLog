"""VoiceScribe CLI — record system audio, transcribe, and manage meetings."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import uuid
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ------------------------------------------------------------------
# Subcommand handlers
# ------------------------------------------------------------------


def cmd_devices(args: argparse.Namespace) -> None:
    """List available audio devices."""
    from src.audio.capture import AudioCapture

    devices = AudioCapture.list_devices()
    loopback_ids = {d["index"] for d in AudioCapture.list_loopback_devices()}

    print(f"{'Idx':<5} {'Loopback':<10} {'Ch':<4} {'Rate':<8} Name")
    print("-" * 70)
    for d in devices:
        lb = "*" if d["index"] in loopback_ids else ""
        print(
            f"{d['index']:<5} {lb:<10} {d['channels']:<4} "
            f"{d['default_sample_rate']:<8} {d['name']}"
        )


def cmd_record(args: argparse.Namespace) -> None:
    """Record system audio, transcribe on stop, save to database."""
    asyncio.run(_record_async(args))


async def _record_async(args: argparse.Namespace) -> None:
    settings = get_settings()
    language = args.language or settings.language
    model = args.model or settings.whisper_model

    from src.audio.capture import AudioCapture
    from src.audio.vad import VoiceActivityDetector
    from src.transcription.engine import TranscriptionEngine
    from src.storage.database import Database
    from src.storage.models import Meeting, Segment
    from src.storage.export import TranscriptExporter

    # --- Initialize components ---
    capture = AudioCapture(device_index=args.device)
    vad = VoiceActivityDetector(sample_rate=settings.sample_rate)
    engine = TranscriptionEngine(
        model_size=model,
        device=settings.whisper_device,
        language=language,
    )
    db = Database(settings.db_path)
    await db.init()

    # --- Start recording ---
    meeting_id = uuid.uuid4().hex
    started_at = datetime.utcnow()

    capture.start()
    print("Recording... Press Ctrl+C to stop.")

    stop_event = asyncio.Event()

    def _signal_handler(sig, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, _signal_handler)

    if args.duration:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=args.duration)
        except asyncio.TimeoutError:
            pass
    else:
        await stop_event.wait()

    # --- Stop recording ---
    capture.stop()
    ended_at = datetime.utcnow()
    duration_seconds = int((ended_at - started_at).total_seconds())
    print(f"Recording stopped. Duration: {duration_seconds}s")

    # Retrieve full captured audio
    full_audio = capture.get_audio(duration_seconds + 1)

    if full_audio.size == 0:
        print("No audio captured.")
        await db.close()
        return

    # --- Save raw audio to disk ---
    settings.audio_save_path.mkdir(parents=True, exist_ok=True)
    audio_path = settings.audio_save_path / f"{meeting_id}.wav"
    _save_wav(audio_path, full_audio, settings.sample_rate)
    print(f"Audio saved to {audio_path}")

    # --- VAD: detect speech segments ---
    print("Detecting speech segments...")
    speech_segments = vad.process(full_audio)
    print(f"Found {len(speech_segments)} speech segment(s).")

    if not speech_segments:
        print("No speech detected in recording.")
        await db.close()
        return

    # --- Transcribe each segment ---
    print("Transcribing...")
    all_segments: list[Segment] = []

    for i, speech in enumerate(speech_segments):
        seg_audio = speech["audio"]
        transcription = engine.transcribe(seg_audio, language=language)

        for t in transcription:
            segment = Segment(
                meeting_id=meeting_id,
                speaker_label="Speaker",
                start_time=round(speech["start"] + t["start"], 3),
                end_time=round(speech["start"] + t["end"], 3),
                text=t["text"],
                confidence=t["confidence"],
            )
            all_segments.append(segment)

    # --- Save to database ---
    meeting = Meeting(
        id=meeting_id,
        title=f"Recording {started_at.strftime('%Y-%m-%d %H:%M')}",
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration_seconds,
        audio_path=str(audio_path),
        language=language,
    )
    await db.create_meeting(meeting)
    if all_segments:
        await db.add_segments(all_segments)
    await db.close()

    # --- Print transcript to console ---
    print()
    print("=" * 60)
    print(f"  Transcript — {meeting.title}")
    print("=" * 60)
    for seg in all_segments:
        ts = _fmt_time(seg.start_time)
        print(f"  [{ts}]  {seg.text}")
    print("=" * 60)
    print(f"Meeting ID: {meeting_id}")
    print()

    # --- Export if requested ---
    if hasattr(args, "output") and args.output:
        exporter = TranscriptExporter(all_segments, meeting)
        out_path = Path(args.output)
        fmt = out_path.suffix.lstrip(".") or "md"
        exporter.save(out_path, format=fmt)
        print(f"Transcript exported to {out_path}")


def cmd_transcribe(args: argparse.Namespace) -> None:
    """Transcribe a .wav file."""
    asyncio.run(_transcribe_async(args))


async def _transcribe_async(args: argparse.Namespace) -> None:
    settings = get_settings()
    language = args.language or settings.language
    model = args.model or settings.whisper_model

    from src.audio.vad import VoiceActivityDetector
    from src.transcription.engine import TranscriptionEngine
    from src.storage.database import Database
    from src.storage.models import Meeting, Segment
    from src.storage.export import TranscriptExporter

    wav_path = Path(args.file)
    if not wav_path.exists():
        print(f"Error: file not found: {wav_path}")
        sys.exit(1)

    # Load WAV file
    audio = _load_wav(wav_path, settings.sample_rate)
    print(f"Loaded {wav_path.name}: {len(audio) / settings.sample_rate:.1f}s of audio")

    # Initialize components
    vad = VoiceActivityDetector(sample_rate=settings.sample_rate)
    engine = TranscriptionEngine(
        model_size=model,
        device=settings.whisper_device,
        language=language,
    )
    db = Database(settings.db_path)
    await db.init()

    # VAD
    print("Detecting speech segments...")
    speech_segments = vad.process(audio)
    print(f"Found {len(speech_segments)} speech segment(s).")

    if not speech_segments:
        print("No speech detected.")
        await db.close()
        return

    # Transcribe
    print("Transcribing...")
    meeting_id = uuid.uuid4().hex
    now = datetime.utcnow()
    duration_seconds = int(len(audio) / settings.sample_rate)
    all_segments: list[Segment] = []

    for speech in speech_segments:
        seg_audio = speech["audio"]
        transcription = engine.transcribe(seg_audio, language=language)

        for t in transcription:
            segment = Segment(
                meeting_id=meeting_id,
                speaker_label="Speaker",
                start_time=round(speech["start"] + t["start"], 3),
                end_time=round(speech["start"] + t["end"], 3),
                text=t["text"],
                confidence=t["confidence"],
            )
            all_segments.append(segment)

    # Save to database
    meeting = Meeting(
        id=meeting_id,
        title=f"Transcription of {wav_path.name}",
        started_at=now,
        ended_at=now,
        duration_seconds=duration_seconds,
        audio_path=str(wav_path),
        language=language,
    )
    await db.create_meeting(meeting)
    if all_segments:
        await db.add_segments(all_segments)
    await db.close()

    # Print transcript
    print()
    print("=" * 60)
    print(f"  Transcript — {wav_path.name}")
    print("=" * 60)
    for seg in all_segments:
        ts = _fmt_time(seg.start_time)
        print(f"  [{ts}]  {seg.text}")
    print("=" * 60)
    print(f"Meeting ID: {meeting_id}")


def cmd_meetings(args: argparse.Namespace) -> None:
    """List saved meetings."""
    asyncio.run(_meetings_async(args))


async def _meetings_async(args: argparse.Namespace) -> None:
    settings = get_settings()
    from src.storage.database import Database

    db = Database(settings.db_path)
    await db.init()
    meetings = await db.list_meetings(limit=args.limit)
    await db.close()

    if not meetings:
        print("No meetings found.")
        return

    print(f"{'ID':<34} {'Date':<20} {'Duration':<10} Title")
    print("-" * 90)
    for m in meetings:
        started = (
            m.started_at.strftime("%Y-%m-%d %H:%M")
            if hasattr(m.started_at, "strftime")
            else str(m.started_at)[:16]
        )
        dur = _fmt_time(m.duration_seconds) if m.duration_seconds else "—"
        title = m.title or "(untitled)"
        print(f"{m.id:<34} {started:<20} {dur:<10} {title}")


def cmd_export(args: argparse.Namespace) -> None:
    """Export a meeting transcript."""
    asyncio.run(_export_async(args))


async def _export_async(args: argparse.Namespace) -> None:
    settings = get_settings()
    from src.storage.database import Database
    from src.storage.export import TranscriptExporter

    db = Database(settings.db_path)
    await db.init()
    meeting = await db.get_meeting(args.meeting_id)

    if meeting is None:
        print(f"Error: meeting not found: {args.meeting_id}")
        await db.close()
        sys.exit(1)

    segments = await db.get_segments(args.meeting_id)
    await db.close()

    exporter = TranscriptExporter(segments, meeting)

    if args.output:
        out_path = Path(args.output)
        exporter.save(out_path, format=args.format)
        print(f"Exported to {out_path}")
    else:
        format_methods = {
            "txt": exporter.to_txt,
            "md": exporter.to_markdown,
            "srt": exporter.to_srt,
            "json": exporter.to_json,
        }
        content = format_methods[args.format]()
        print(content)


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the JSON-RPC server for Tauri sidecar mode."""
    asyncio.run(_serve_async(args))


async def _serve_async(args: argparse.Namespace) -> None:
    try:
        from src.ipc import JsonRpcHandler
    except ImportError:
        print("Error: IPC module not available. Install src.ipc to use serve mode.")
        sys.exit(1)

    logger.info("Starting JSON-RPC server...")
    handler = JsonRpcHandler()
    await handler.run()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _fmt_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _save_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    """Save float32 mono audio as a 16-bit WAV file."""
    pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def _load_wav(path: Path, target_sr: int) -> np.ndarray:
    """Load a WAV file and return float32 mono audio at *target_sr*."""
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    if sampwidth == 2:
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        audio = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported sample width: {sampwidth}")

    # Down-mix to mono
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)

    # Resample if needed
    if framerate != target_sr:
        duration = len(audio) / framerate
        target_len = int(duration * target_sr)
        indices = np.linspace(0, len(audio) - 1, target_len)
        audio = np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)

    return audio


# ------------------------------------------------------------------
# Argument parser
# ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    settings = get_settings()

    parser = argparse.ArgumentParser(
        prog="voicescribe",
        description="VoiceScribe — record system audio, transcribe, and manage meetings.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- record ---
    p_record = subparsers.add_parser("record", help="Record system audio and transcribe")
    p_record.add_argument(
        "--device", type=int, default=None, help="Audio device index"
    )
    p_record.add_argument(
        "--duration", type=int, default=None, help="Record for N seconds then auto-stop"
    )
    p_record.add_argument(
        "--language", type=str, default=None,
        help=f"Transcription language (default: {settings.language})",
    )
    p_record.add_argument(
        "--model", type=str, default=None,
        help=f"Whisper model size (default: {settings.whisper_model})",
    )
    p_record.add_argument(
        "--output", type=str, default=None, help="Export transcript to file"
    )

    # --- devices ---
    subparsers.add_parser("devices", help="List available audio devices")

    # --- transcribe ---
    p_transcribe = subparsers.add_parser("transcribe", help="Transcribe a .wav file")
    p_transcribe.add_argument(
        "--file", type=str, required=True, help="Path to .wav file"
    )
    p_transcribe.add_argument("--language", type=str, default=None, help="Language code")
    p_transcribe.add_argument("--model", type=str, default=None, help="Whisper model size")

    # --- meetings ---
    p_meetings = subparsers.add_parser("meetings", help="List saved meetings")
    p_meetings.add_argument(
        "--limit", type=int, default=20, help="Max number of meetings to show"
    )

    # --- export ---
    p_export = subparsers.add_parser("export", help="Export a meeting transcript")
    p_export.add_argument("--meeting-id", type=str, required=True, help="Meeting ID")
    p_export.add_argument(
        "--format", type=str, default="md",
        choices=["txt", "md", "srt", "json"],
        help="Export format (default: md)",
    )
    p_export.add_argument("--output", type=str, default=None, help="Output file path")

    # --- serve ---
    subparsers.add_parser("serve", help="Start JSON-RPC server (Tauri sidecar mode)")

    return parser


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    handlers = {
        "record": cmd_record,
        "devices": cmd_devices,
        "transcribe": cmd_transcribe,
        "meetings": cmd_meetings,
        "export": cmd_export,
        "serve": cmd_serve,
    }

    handler = handlers.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
