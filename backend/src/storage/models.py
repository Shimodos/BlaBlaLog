"""Pydantic models for the data/storage layer."""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Speaker(BaseModel):
    """Known speaker with voice embedding for identification."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    embedding: bytes = Field(default=b"", description="Speaker voice embedding (numpy bytes)")
    sample_audio_path: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Meeting(BaseModel):
    """A single recorded meeting / conversation session."""

    id: str = Field(..., description="UUID string")
    title: Optional[str] = None
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    audio_path: Optional[str] = None
    language: str = "ru"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Segment(BaseModel):
    """One speech segment inside a meeting transcript."""

    id: Optional[int] = None
    meeting_id: str
    speaker_id: Optional[str] = None
    speaker_label: str
    start_time: float
    end_time: float
    text: str
    confidence: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TranscriptLine(BaseModel):
    """Lightweight display-only line used for rendering transcripts."""

    speaker_label: str
    start_time: float
    end_time: float
    text: str
