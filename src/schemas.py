from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    ERROR = "ERROR"


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    error: str | None = None


class Document(BaseModel):
    job_id: str
    content_hash: str
    title: str
    content: str
    source: str  # file path, URL, arXiv ID, etc.
    language: str | None = None  # relevant for embeddings and search
    metadata: dict[str, Any] = Field(default_factory=dict)
    processing_time_ms: int | None = None
    processed_at: datetime = Field(default_factory=datetime.now)