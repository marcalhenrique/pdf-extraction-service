from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Possible states of a conversion job."""

    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    ERROR = "ERROR"


class JobResponse(BaseModel):
    """API response representing the current state of a job."""

    job_id: str
    status: JobStatus
    queue_size: int | None = None
    error: str | None = None


class Document(BaseModel):
    """Extracted document with content and metadata."""

    job_id: str
    content_hash: str
    title: str
    content_url: str
    images_url: dict[str, str] = Field(default_factory=dict)
    source: str  # file path, URL, arXiv ID, etc.
    language: str | None = None  # relevant for embeddings and search
    metadata: dict[str, Any] = Field(default_factory=dict)
    processing_time_ms: int | None = None
    processed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))