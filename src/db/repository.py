from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import DocumentModel
from src.schemas import Document


async def save(session: AsyncSession, document: Document) -> None:
    """Persist a Document to the database."""
    model = DocumentModel(
        job_id=document.job_id,
        content_hash=document.content_hash,
        title=document.title,
        content_url=document.content_url,
        images_url=document.images_url,
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

async def get_all(session: AsyncSession) -> list[Document]:
    """Fetch all documents from the database."""
    result = await session.execute(select(DocumentModel))
    models = result.scalars().all()
    return [_to_document(model) for model in models]

async def get_by_title(session: AsyncSession, title: str) -> list[Document]:
    """Fetch documents with titles containing the given string."""
    escaped = (
        title.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    result = await session.execute(
        select(DocumentModel).where(
            DocumentModel.title.ilike(f"%{escaped}%", escape="\\")
        )
    )
    models = result.scalars().all()
    return [_to_document(model) for model in models]


async def get_by_hash(session: AsyncSession, content_hash: str) -> Document | None:
    """Fetch a document by content hash, or return None."""
    result = await session.execute(
        select(DocumentModel).where(DocumentModel.content_hash == content_hash)
    )
    model = result.scalar_one_or_none()
    return _to_document(model) if model else None

async def delete_by_job_id(session: AsyncSession, job_id: str) -> bool:
    """Delete a document by job ID. Returns True if deleted, False if not found."""
    result = await session.execute(
        delete(DocumentModel).where(DocumentModel.job_id == job_id)
    )
    await session.commit()
    return result.rowcount > 0


def _to_document(model: DocumentModel) -> Document:
    """Convert a DocumentModel ORM instance to a Document schema."""
    return Document(
        job_id=model.job_id,
        content_hash=model.content_hash,
        title=model.title,
        content_url=model.content_url,
        images_url=model.images_url,
        source=model.source,
        language=model.language,
        metadata=model.metadata_,
        processing_time_ms=model.processing_time_ms,
        processed_at=model.processed_at,
    )
