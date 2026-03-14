from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    done = "done"
    error = "error"


class DocumentType(str, Enum):
    pdf = "pdf"



class JobResponse(BaseModel):
    job_id: str
    status: JobStatus


class ResultResponse(BaseModel):
    job_id: str
    status: JobStatus
    document: Document | None = None
    error: str | None = None


class Document(BaseModel):
    doc_id: str
    title: str
    content: str
    doc_type: DocumentType
    source: str  # file path, URL, arXiv ID, etc.
    language: str | None = None  # relevant for code files (e.g. "python")
    metadata: dict[str, Any] = Field(default_factory=dict)
    ingested_at: datetime = Field(default_factory=datetime.now)  # uses TZ set by config (os.environ["TZ"])
    