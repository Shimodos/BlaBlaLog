"""Async SQLite database layer using aiosqlite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite

from src.storage.models import Meeting, Segment, Speaker


class Database:
    """Async wrapper around an SQLite database for meetings, segments, and speakers."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Open the connection and create tables if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._create_tables()
        await self._migrate()

    async def _create_tables(self) -> None:
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS meetings (
                id            TEXT PRIMARY KEY,
                title         TEXT,
                started_at    TEXT NOT NULL,
                ended_at      TEXT,
                duration_seconds INTEGER,
                audio_path    TEXT,
                language      TEXT NOT NULL DEFAULT 'ru',
                created_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS speakers (
                id                TEXT PRIMARY KEY,
                name              TEXT NOT NULL,
                embedding         BLOB DEFAULT x'',
                sample_audio_path TEXT,
                created_at        TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS segments (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                meeting_id    TEXT NOT NULL,
                speaker_id    TEXT,
                speaker_label TEXT NOT NULL,
                start_time    REAL NOT NULL,
                end_time      REAL NOT NULL,
                text          TEXT NOT NULL,
                confidence    REAL,
                created_at    TEXT NOT NULL,
                FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE,
                FOREIGN KEY (speaker_id) REFERENCES speakers(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_segments_meeting
                ON segments(meeting_id);
            CREATE INDEX IF NOT EXISTS idx_segments_speaker
                ON segments(speaker_id);
            """
        )

    async def _migrate(self) -> None:
        """Run lightweight schema migrations for existing databases."""
        # Fix: speakers.embedding was NOT NULL in early schema, make it nullable
        try:
            cursor = await self._db.execute("PRAGMA table_info(speakers)")
            columns = await cursor.fetchall()
            for col in columns:
                if col["name"] == "embedding" and col["notnull"] == 1:
                    # Recreate table with relaxed constraint
                    await self._db.executescript("""
                        CREATE TABLE IF NOT EXISTS speakers_new (
                            id                TEXT PRIMARY KEY,
                            name              TEXT NOT NULL,
                            embedding         BLOB DEFAULT x'',
                            sample_audio_path TEXT,
                            created_at        TEXT NOT NULL
                        );
                        INSERT OR IGNORE INTO speakers_new SELECT * FROM speakers;
                        DROP TABLE speakers;
                        ALTER TABLE speakers_new RENAME TO speakers;
                    """)
                    break
        except Exception:
            pass  # Migration is best-effort

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> "Database":
        await self.init()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        await self.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _dt(val: Any) -> str | None:
        """Serialize a datetime (or None) to ISO-8601 string."""
        if val is None:
            return None
        return val.isoformat() if not isinstance(val, str) else val

    # ------------------------------------------------------------------
    # Meetings
    # ------------------------------------------------------------------

    async def create_meeting(self, meeting: Meeting) -> str:
        await self._db.execute(
            """
            INSERT INTO meetings (id, title, started_at, ended_at,
                                  duration_seconds, audio_path, language, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                meeting.id,
                meeting.title,
                self._dt(meeting.started_at),
                self._dt(meeting.ended_at),
                meeting.duration_seconds,
                meeting.audio_path,
                meeting.language,
                self._dt(meeting.created_at),
            ),
        )
        await self._db.commit()
        return meeting.id

    async def update_meeting(self, meeting_id: str, **kwargs: Any) -> None:
        if not kwargs:
            return
        # Serialize datetime values
        for key in ("started_at", "ended_at", "created_at"):
            if key in kwargs:
                kwargs[key] = self._dt(kwargs[key])
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [meeting_id]
        await self._db.execute(
            f"UPDATE meetings SET {sets} WHERE id = ?", values  # noqa: S608
        )
        await self._db.commit()

    async def get_meeting(self, meeting_id: str) -> Meeting | None:
        async with self._db.execute(
            "SELECT * FROM meetings WHERE id = ?", (meeting_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return self._row_to_meeting(row)

    async def list_meetings(self, limit: int = 50, offset: int = 0) -> list[Meeting]:
        async with self._db.execute(
            "SELECT * FROM meetings ORDER BY started_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_meeting(r) for r in rows]

    async def delete_meeting(self, meeting_id: str) -> None:
        await self._db.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
        await self._db.commit()

    @staticmethod
    def _row_to_meeting(row: aiosqlite.Row) -> Meeting:
        return Meeting(
            id=row["id"],
            title=row["title"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            duration_seconds=row["duration_seconds"],
            audio_path=row["audio_path"],
            language=row["language"],
            created_at=row["created_at"],
        )

    # ------------------------------------------------------------------
    # Segments
    # ------------------------------------------------------------------

    async def add_segment(self, segment: Segment) -> int:
        async with self._db.execute(
            """
            INSERT INTO segments (meeting_id, speaker_id, speaker_label,
                                  start_time, end_time, text, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                segment.meeting_id,
                segment.speaker_id,
                segment.speaker_label,
                segment.start_time,
                segment.end_time,
                segment.text,
                segment.confidence,
                self._dt(segment.created_at),
            ),
        ) as cur:
            row_id = cur.lastrowid
        await self._db.commit()
        return row_id

    async def add_segments(self, segments: list[Segment]) -> None:
        await self._db.executemany(
            """
            INSERT INTO segments (meeting_id, speaker_id, speaker_label,
                                  start_time, end_time, text, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    s.meeting_id,
                    s.speaker_id,
                    s.speaker_label,
                    s.start_time,
                    s.end_time,
                    s.text,
                    s.confidence,
                    self._dt(s.created_at),
                )
                for s in segments
            ],
        )
        await self._db.commit()

    async def get_segments(self, meeting_id: str) -> list[Segment]:
        async with self._db.execute(
            "SELECT * FROM segments WHERE meeting_id = ? ORDER BY start_time",
            (meeting_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [
            Segment(
                id=r["id"],
                meeting_id=r["meeting_id"],
                speaker_id=r["speaker_id"],
                speaker_label=r["speaker_label"],
                start_time=r["start_time"],
                end_time=r["end_time"],
                text=r["text"],
                confidence=r["confidence"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Speakers
    # ------------------------------------------------------------------

    async def create_speaker(self, speaker: Speaker) -> str:
        await self._db.execute(
            """
            INSERT INTO speakers (id, name, embedding, sample_audio_path, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                speaker.id,
                speaker.name,
                speaker.embedding,
                speaker.sample_audio_path,
                self._dt(speaker.created_at),
            ),
        )
        await self._db.commit()
        return speaker.id

    async def get_speaker(self, speaker_id: str) -> Speaker | None:
        async with self._db.execute(
            "SELECT * FROM speakers WHERE id = ?", (speaker_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return self._row_to_speaker(row)

    async def list_speakers(self) -> list[Speaker]:
        async with self._db.execute(
            "SELECT * FROM speakers ORDER BY name"
        ) as cur:
            rows = await cur.fetchall()
        return [self._row_to_speaker(r) for r in rows]

    async def update_speaker(self, speaker_id: str, **kwargs: Any) -> None:
        if not kwargs:
            return
        if "created_at" in kwargs:
            kwargs["created_at"] = self._dt(kwargs["created_at"])
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [speaker_id]
        await self._db.execute(
            f"UPDATE speakers SET {sets} WHERE id = ?", values  # noqa: S608
        )
        await self._db.commit()

    async def add_speaker(self, speaker: Speaker) -> None:
        await self._db.execute(
            "INSERT INTO speakers (id, name, created_at) VALUES (?, ?, ?)",
            (speaker.id, speaker.name, str(speaker.created_at)),
        )
        await self._db.commit()

    async def delete_speaker(self, speaker_id: str) -> None:
        await self._db.execute("DELETE FROM speakers WHERE id = ?", (speaker_id,))
        await self._db.commit()

    @staticmethod
    def _row_to_speaker(row: aiosqlite.Row) -> Speaker:
        return Speaker(
            id=row["id"],
            name=row["name"],
            embedding=bytes(row["embedding"]),
            sample_audio_path=row["sample_audio_path"],
            created_at=row["created_at"],
        )
