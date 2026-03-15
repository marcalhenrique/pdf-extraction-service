from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import DocumentModel
from src.schemas import Document


async def save(session: AsyncSession, document: Document) -> None:
    """Persist a Document to the database."""
    model = DocumentModel(
        job_id=document.job_id,
        content_hash=document.content_hash,
        title=document.title,
        content=document.content,
        source=document.source,
        language=document.language,
        metadata_=document.metadata,
        processing_time_ms=document.processing_time_ms,
        processed_at=document.processed_at,
    )
    session.add(model)
    await session.commit()


async def get_by_job_id(session: AsyncSession, job_id: str) -> Document | None:
    """Fetch a document by job ID, or return None."""
    result = await session.execute(
        select(DocumentModel).where(DocumentModel.job_id == job_id)
    )
    model = result.scalar_one_or_none()
    return _to_document(model) if model else None


async def get_by_hash(session: AsyncSession, content_hash: str) -> Document | None:
    """Fetch a document by content hash, or return None."""
    result = await session.execute(
        select(DocumentModel).where(DocumentModel.content_hash == content_hash)
    )
    model = result.scalar_one_or_none()
    return _to_document(model) if model else None


def _to_document(model: DocumentModel) -> Document:
    """Convert a DocumentModel ORM instance to a Document schema."""
    return Document(
        job_id=model.job_id,
        content_hash=model.content_hash,
        title=model.title,
        content=model.content,
        source=model.source,
        language=model.language,
        metadata=model.metadata_,
        processing_time_ms=model.processing_time_ms,
        processed_at=model.processed_at,
    )
