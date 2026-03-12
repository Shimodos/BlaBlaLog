"""Shared fixtures for BlaBlaLog backend tests."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
import pytest_asyncio

from src.storage.database import Database
from src.storage.models import Meeting, Segment, Speaker


@pytest_asyncio.fixture
async def db():
    """Create an in-memory Database, initialise tables, yield, then close."""
    database = Database(":memory:")
    await database.init()
    yield database
    await database.close()


@pytest.fixture
def sample_meeting() -> Meeting:
    """Return a pre-built Meeting model for use in tests."""
    return Meeting(
        id=str(uuid.uuid4()),
        title="Weekly Standup",
        started_at=datetime(2025, 6, 1, 10, 0, 0),
        ended_at=datetime(2025, 6, 1, 10, 30, 0),
        duration_seconds=1800,
        audio_path="/tmp/audio/meeting.wav",
        language="en",
        created_at=datetime(2025, 6, 1, 10, 0, 0),
    )


@pytest.fixture
def sample_segments(sample_meeting) -> list[Segment]:
    """Return a list of Segment models tied to `sample_meeting`."""
    mid = sample_meeting.id
    return [
        Segment(
            meeting_id=mid,
            speaker_id=None,
            speaker_label="Speaker 1",
            start_time=0.0,
            end_time=5.5,
            text="Hello everyone, let's start the meeting.",
            confidence=0.92,
            created_at=datetime(2025, 6, 1, 10, 0, 0),
        ),
        Segment(
            meeting_id=mid,
            speaker_id=None,
            speaker_label="Speaker 2",
            start_time=5.5,
            end_time=12.3,
            text="Sure, I have an update on the backend progress.",
            confidence=0.88,
            created_at=datetime(2025, 6, 1, 10, 0, 6),
        ),
        Segment(
            meeting_id=mid,
            speaker_id=None,
            speaker_label="Speaker 1",
            start_time=12.3,
            end_time=18.0,
            text="Great, go ahead.",
            confidence=0.95,
            created_at=datetime(2025, 6, 1, 10, 0, 12),
        ),
    ]


@pytest.fixture
def sample_speaker() -> Speaker:
    """Return a pre-built Speaker model for use in tests."""
    return Speaker(
        id=str(uuid.uuid4()),
        name="Alice",
        embedding=b"\x00\x01\x02\x03" * 32,
        sample_audio_path="/tmp/audio/alice_sample.wav",
        created_at=datetime(2025, 6, 1, 9, 0, 0),
    )
