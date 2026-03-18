import asyncio
import hashlib
import httpx

from structlog import get_logger
from fastapi import APIRouter, Request, UploadFile, Query, HTTPException
from fastapi.responses import JSONResponse

from src.db.database import async_session
from src.db import repository
from src.schemas import JobStatus, JobResponse, Document
from src.storage import MDStorage

logger = get_logger(__name__)

router = APIRouter()


@router.post("/convert", status_code=202, response_model=None)
async def convert_pdf(request: Request, file: UploadFile) -> JobResponse | JSONResponse:
    """Accept a PDF upload and enqueue it for conversion."""
    pdf_bytes = await file.read()
    
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    
    content_hash = hashlib.sha256(pdf_bytes).hexdigest()[:16]
    async with async_session() as session:
        existing = await repository.get_by_hash(session, content_hash)
    if existing:
        logger.info("duplicate_detected", content_hash=content_hash, job_id=existing.job_id)
        return JSONResponse(
            status_code=200,
            content=existing.model_dump(mode="json"),
        )
    
    try:
        job_id = request.app.state.job_manager.enqueue(pdf_bytes, source=file.filename)
    except asyncio.QueueFull:
        return JSONResponse(
            status_code=503,
            content={"detail": "Job queue is full. Please try again later."},
        )
        
    return JobResponse(job_id=job_id, status=JobStatus.QUEUED, queue_size=request.app.state.job_manager.queue_size)

@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job_status(request: Request, job_id: str) -> JobResponse:
    """Return the current status of a conversion job."""
    job = request.app.state.job_manager.get_job(job_id)
    
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    
    return JobResponse(
        job_id=job.job_id,
        status=job.status,
        error=job.error,
        queue_size=request.app.state.job_manager.queue_size,
    )


@router.get("/documents", response_model=list[Document])
async def get_all_documents() -> list[Document]:
    """Retrieve all extracted documents."""
    async with async_session() as session:
        documents = await repository.get_all(session)
    return documents


@router.get("/documents/search", response_model=list[Document])
async def search_documents(title: str = Query(..., description="Search documents by title")) -> list[Document]:
    """Search documents by title."""
    async with async_session() as session:
        documents = await repository.get_by_title(session, title)
    return documents


@router.get("/documents/{job_id}", response_model=Document)
async def get_document(job_id: str) -> Document:
    """Retrieve the extracted document by job ID."""
    async with async_session() as session:
        document = await repository.get_by_job_id(session, job_id)
    
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    
    return document


@router.delete("/documents/{job_id}", status_code=204)
async def delete_document(request: Request, job_id: str) -> None:
    """Delete a document by job ID."""
    async with async_session() as session:
        deleted = await repository.delete_by_job_id(session, job_id)
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found.")
    
    storage: MDStorage = request.app.state.storage
    await asyncio.to_thread(storage.delete_document, job_id)


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Liveness probe endpoint."""
    return {"status": "ok"}