"""Export meeting transcripts to TXT, Markdown, SRT, and JSON."""

from __future__ import annotations

import json
from pathlib import Path

from src.storage.models import Meeting, Segment


def _fmt_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS (for display)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_srt_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS,mmm (SRT standard)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class TranscriptExporter:
    """Converts a list of segments + meeting metadata into various text formats."""

    def __init__(self, segments: list[Segment], meeting: Meeting) -> None:
        self.segments = segments
        self.meeting = meeting

    # ------------------------------------------------------------------
    # Plain text
    # ------------------------------------------------------------------

    def to_txt(
        self,
        include_timestamps: bool = True,
        include_speakers: bool = True,
    ) -> str:
        lines: list[str] = []
        if self.meeting.title:
            lines.append(self.meeting.title)
            lines.append("=" * len(self.meeting.title))
            lines.append("")

        for seg in self.segments:
            parts: list[str] = []
            if include_timestamps:
                parts.append(f"[{_fmt_time(seg.start_time)} - {_fmt_time(seg.end_time)}]")
            if include_speakers:
                parts.append(f"{seg.speaker_label}:")
            parts.append(seg.text)
            lines.append(" ".join(parts))

        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Markdown
    # ------------------------------------------------------------------

    def to_markdown(self, include_timestamps: bool = True) -> str:
        lines: list[str] = []

        title = self.meeting.title or "Transcript"
        lines.append(f"# {title}")
        lines.append("")
        lines.append(
            f"**Date:** {self.meeting.started_at.isoformat() if hasattr(self.meeting.started_at, 'isoformat') else self.meeting.started_at}  "
        )
        if self.meeting.duration_seconds is not None:
            lines.append(f"**Duration:** {_fmt_time(self.meeting.duration_seconds)}  ")
        lines.append(f"**Language:** {self.meeting.language}  ")
        lines.append("")
        lines.append("---")
        lines.append("")

        for seg in self.segments:
            ts = ""
            if include_timestamps:
                ts = f" `{_fmt_time(seg.start_time)}-{_fmt_time(seg.end_time)}`"
            lines.append(f"**{seg.speaker_label}**{ts}  ")
            lines.append(seg.text)
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # SRT (SubRip subtitle)
    # ------------------------------------------------------------------

    def to_srt(self) -> str:
        blocks: list[str] = []
        for idx, seg in enumerate(self.segments, start=1):
            start = _fmt_srt_time(seg.start_time)
            end = _fmt_srt_time(seg.end_time)
            blocks.append(
                f"{idx}\n{start} --> {end}\n{seg.speaker_label}: {seg.text}"
            )
        return "\n\n".join(blocks) + "\n"

    # ------------------------------------------------------------------
    # JSON
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        data = {
            "meeting": {
                "id": self.meeting.id,
                "title": self.meeting.title,
                "started_at": (
                    self.meeting.started_at.isoformat()
                    if hasattr(self.meeting.started_at, "isoformat")
                    else str(self.meeting.started_at)
                ),
                "language": self.meeting.language,
                "duration_seconds": self.meeting.duration_seconds,
            },
            "segments": [
                {
                    "speaker": seg.speaker_label,
                    "start": seg.start_time,
                    "end": seg.end_time,
                    "text": seg.text,
                    "confidence": seg.confidence,
                }
                for seg in self.segments
            ],
        }
        return json.dumps(data, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # Save to file
    # ------------------------------------------------------------------

    def save(self, path: Path, format: str = "md") -> None:
        """Write transcript to *path* in the given format (txt, md, srt, json)."""
        exporters = {
            "txt": self.to_txt,
            "md": self.to_markdown,
            "srt": self.to_srt,
            "json": self.to_json,
        }
        fn = exporters.get(format)
        if fn is None:
            raise ValueError(
                f"Unknown format '{format}'. Supported: {', '.join(exporters)}"
            )
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(fn(), encoding="utf-8")
