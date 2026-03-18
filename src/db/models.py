from datetime import datetime

from sqlalchemy import String, Text, DateTime, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.db.database import Base

class DocumentModel(Base):
    """SQLAlchemy model for the documents table."""

    __tablename__ = "documents"
    
    job_id: Mapped[str] = mapped_column(String(12), nullable=False, primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(16), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    content_url: Mapped[str] = mapped_column(String, nullable=False)
    images_url: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    source: Mapped[str] = mapped_column(String, nullable=False)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)