"""Tests for database, models, and export (src.storage).

Uses an in-memory SQLite database and pytest-asyncio for async tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
import pytest_asyncio

from src.storage.database import Database
from src.storage.export import TranscriptExporter
from src.storage.models import Meeting, Segment, Speaker, TranscriptLine


# ===================================================================
# Model creation tests
# ===================================================================

class TestModelsCreation:
    def test_speaker_model(self):
        speaker = Speaker(
            id="sp-1",
            name="Bob",
            embedding=b"\x00" * 16,
        )
        assert speaker.id == "sp-1"
        assert speaker.name == "Bob"
        assert isinstance(speaker.embedding, bytes)
        assert isinstance(speaker.created_at, datetime)
        assert speaker.sample_audio_path is None

    def test_meeting_model(self):
        meeting = Meeting(
            id="mtg-1",
            title="Sprint Review",
            started_at=datetime(2025, 1, 1, 9, 0),
            language="en",
        )
        assert meeting.id == "mtg-1"
        assert meeting.title == "Sprint Review"
        assert meeting.language == "en"
        assert meeting.ended_at is None
        assert meeting.duration_seconds is None

    def test_segment_model(self):
        segment = Segment(
            meeting_id="mtg-1",
            speaker_label="Speaker 1",
            start_time=0.0,
            end_time=3.5,
            text="Hello",
        )
        assert segment.meeting_id == "mtg-1"
        assert segment.speaker_label == "Speaker 1"
        assert segment.id is None
        assert segment.speaker_id is None
        assert segment.confidence is None

    def test_transcript_line_model(self):
        line = TranscriptLine(
            speaker_label="Speaker 1",
            start_time=0.0,
            end_time=2.0,
            text="Test line",
        )
        assert line.text == "Test line"


# ===================================================================
# Database init
# ===================================================================

class TestDatabaseInit:
    @pytest.mark.asyncio
    async def test_tables_created(self, db: Database):
        """Verify that all three tables exist after init."""
        async with db._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) as cur:
            rows = await cur.fetchall()
        table_names = {r["name"] for r in rows}
        assert "meetings" in table_names
        assert "segments" in table_names
        assert "speakers" in table_names


# ===================================================================
# Meeting CRUD
# ===================================================================

class TestMeetingCrud:
    @pytest.mark.asyncio
    async def test_create_and_get(self, db: Database, sample_meeting: Meeting):
        mid = await db.create_meeting(sample_meeting)
        assert mid == sample_meeting.id

        fetched = await db.get_meeting(mid)
        assert fetched is not None
        assert fetched.id == sample_meeting.id
        assert fetched.title == sample_meeting.title
        assert fetched.language == sample_meeting.language

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, db: Database):
        result = await db.get_meeting("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_meetings(self, db: Database, sample_meeting: Meeting):
        await db.create_meeting(sample_meeting)

        # Create a second meeting
        m2 = Meeting(
            id=str(uuid.uuid4()),
            title="Second Meeting",
            started_at=datetime(2025, 7, 1, 14, 0, 0),
            language="ru",
            created_at=datetime(2025, 7, 1, 14, 0, 0),
        )
        await db.create_meeting(m2)

        meetings = await db.list_meetings()
        assert len(meetings) == 2

    @pytest.mark.asyncio
    async def test_update_meeting(self, db: Database, sample_meeting: Meeting):
        await db.create_meeting(sample_meeting)
        await db.update_meeting(sample_meeting.id, title="Updated Title", duration_seconds=900)

        fetched = await db.get_meeting(sample_meeting.id)
        assert fetched.title == "Updated Title"
        assert fetched.duration_seconds == 900

    @pytest.mark.asyncio
    async def test_delete_meeting(self, db: Database, sample_meeting: Meeting):
        await db.create_meeting(sample_meeting)
        await db.delete_meeting(sample_meeting.id)

        fetched = await db.get_meeting(sample_meeting.id)
        assert fetched is None


# ===================================================================
# Segment CRUD
# ===================================================================

class TestSegmentCrud:
    @pytest.mark.asyncio
    async def test_add_and_get_segments(
        self, db: Database, sample_meeting: Meeting, sample_segments: list[Segment]
    ):
        await db.create_meeting(sample_meeting)

        for seg in sample_segments:
            await db.add_segment(seg)

        fetched = await db.get_segments(sample_meeting.id)
        assert len(fetched) == len(sample_segments)

        # Verify ordering by start_time
        for i in range(len(fetched) - 1):
            assert fetched[i].start_time <= fetched[i + 1].start_time

    @pytest.mark.asyncio
    async def test_add_segments_bulk(
        self, db: Database, sample_meeting: Meeting, sample_segments: list[Segment]
    ):
        await db.create_meeting(sample_meeting)
        await db.add_segments(sample_segments)

        fetched = await db.get_segments(sample_meeting.id)
        assert len(fetched) == len(sample_segments)

    @pytest.mark.asyncio
    async def test_segment_has_auto_id(
        self, db: Database, sample_meeting: Meeting, sample_segments: list[Segment]
    ):
        await db.create_meeting(sample_meeting)
        row_id = await db.add_segment(sample_segments[0])
        assert isinstance(row_id, int)
        assert row_id >= 1

    @pytest.mark.asyncio
    async def test_get_segments_empty(self, db: Database, sample_meeting: Meeting):
        await db.create_meeting(sample_meeting)
        fetched = await db.get_segments(sample_meeting.id)
        assert fetched == []


# ===================================================================
# Speaker CRUD
# ===================================================================

class TestSpeakerCrud:
    @pytest.mark.asyncio
    async def test_create_and_get(self, db: Database, sample_speaker: Speaker):
        sid = await db.create_speaker(sample_speaker)
        assert sid == sample_speaker.id

        fetched = await db.get_speaker(sid)
        assert fetched is not None
        assert fetched.name == sample_speaker.name
        assert fetched.embedding == sample_speaker.embedding

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, db: Database):
        result = await db.get_speaker("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_speakers(self, db: Database, sample_speaker: Speaker):
        await db.create_speaker(sample_speaker)

        sp2 = Speaker(
            id=str(uuid.uuid4()),
            name="Bob",
            embedding=b"\xff" * 32,
        )
        await db.create_speaker(sp2)

        speakers = await db.list_speakers()
        assert len(speakers) == 2
        # list_speakers orders by name
        assert speakers[0].name == "Alice"
        assert speakers[1].name == "Bob"

    @pytest.mark.asyncio
    async def test_update_speaker(self, db: Database, sample_speaker: Speaker):
        await db.create_speaker(sample_speaker)
        await db.update_speaker(sample_speaker.id, name="Alice Updated")

        fetched = await db.get_speaker(sample_speaker.id)
        assert fetched.name == "Alice Updated"

    @pytest.mark.asyncio
    async def test_delete_speaker(self, db: Database, sample_speaker: Speaker):
        await db.create_speaker(sample_speaker)
        await db.delete_speaker(sample_speaker.id)

        fetched = await db.get_speaker(sample_speaker.id)
        assert fetched is None


# ===================================================================
# Export tests
# ===================================================================

class TestExportTxt:
    def test_txt_contains_title_and_segments(self, sample_meeting, sample_segments):
        exporter = TranscriptExporter(sample_segments, sample_meeting)
        txt = exporter.to_txt()

        assert sample_meeting.title in txt
        assert "Speaker 1:" in txt
        assert "Speaker 2:" in txt
        assert "Hello everyone" in txt

    def test_txt_with_timestamps(self, sample_meeting, sample_segments):
        exporter = TranscriptExporter(sample_segments, sample_meeting)
        txt = exporter.to_txt(include_timestamps=True)

        assert "[00:00:00 - 00:00:05]" in txt

    def test_txt_without_timestamps(self, sample_meeting, sample_segments):
        exporter = TranscriptExporter(sample_segments, sample_meeting)
        txt = exporter.to_txt(include_timestamps=False)

        assert "[" not in txt

    def test_txt_without_speakers(self, sample_meeting, sample_segments):
        exporter = TranscriptExporter(sample_segments, sample_meeting)
        txt = exporter.to_txt(include_speakers=False)

        assert "Speaker 1:" not in txt


class TestExportMarkdown:
    def test_markdown_has_title_heading(self, sample_meeting, sample_segments):
        exporter = TranscriptExporter(sample_segments, sample_meeting)
        md = exporter.to_markdown()

        assert md.startswith(f"# {sample_meeting.title}")

    def test_markdown_has_metadata(self, sample_meeting, sample_segments):
        exporter = TranscriptExporter(sample_segments, sample_meeting)
        md = exporter.to_markdown()

        assert "**Date:**" in md
        assert "**Language:** en" in md
        assert "**Duration:** 00:30:00" in md

    def test_markdown_has_speaker_segments(self, sample_meeting, sample_segments):
        exporter = TranscriptExporter(sample_segments, sample_meeting)
        md = exporter.to_markdown()

        assert "**Speaker 1**" in md
        assert "**Speaker 2**" in md


class TestExportSrt:
    def test_srt_format(self, sample_meeting, sample_segments):
        exporter = TranscriptExporter(sample_segments, sample_meeting)
        srt = exporter.to_srt()

        lines = srt.strip().split("\n")

        # First block: sequence number
        assert lines[0] == "1"
        # Second line: timestamps
        assert "-->" in lines[1]
        assert "00:00:00,000 --> 00:00:05,500" in lines[1]
        # Third line: speaker + text
        assert "Speaker 1:" in lines[2]

    def test_srt_has_correct_number_of_blocks(self, sample_meeting, sample_segments):
        exporter = TranscriptExporter(sample_segments, sample_meeting)
        srt = exporter.to_srt()

        # Blocks separated by double newlines
        blocks = srt.strip().split("\n\n")
        assert len(blocks) == len(sample_segments)

    def test_srt_millisecond_timestamps(self, sample_meeting, sample_segments):
        exporter = TranscriptExporter(sample_segments, sample_meeting)
        srt = exporter.to_srt()

        # Second segment starts at 5.5s = 00:00:05,500
        assert "00:00:05,500" in srt
        # Second segment ends at 12.3s = 00:00:12,300
        assert "00:00:12,300" in srt
