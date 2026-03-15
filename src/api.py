from __future__ import annotations

import asyncio
import hashlib
import structlog

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import JSONResponse

from src.config import get_settings
from src.converter import PDFConverter
from src.schemas import JobStatus, JobResponse, Document
from src.worker import JobManager
from src.db.database import async_session
from src.db import repository

settings = get_settings()
logger = structlog.get_logger(__name__)


@asynccontextmanager    
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: load models, warmup, and start background workers."""
    
    # load models
    converter = PDFConverter(torch_device=settings.torch_device)
    
    # warmup
    try:
        warmup_bytes = Path("static/warmup.pdf").read_bytes()
        await asyncio.to_thread(converter.convert, warmup_bytes, "warmup", "warmup")
        logger.info("warmup_completed", torch_device=settings.torch_device)
    except Exception as e:
        logger.warning("warmup_failed", error=str(e))
    
    job_manager = JobManager()
    app.state.job_manager = job_manager
    
    worker_task = asyncio.create_task(job_manager.process_queue(converter))
    cleanup_task = asyncio.create_task(job_manager.cleanup_old_jobs())
    logger.info("worker_tasks_started")
    yield
    
    worker_task.cancel()
    cleanup_task.cancel()
    logger.info("worker_tasks_cancelled")

app = FastAPI(lifespan=_lifespan)


@app.post("/converter", status_code=202, response_model=None)
async def convert_pdf(file: UploadFile) -> JobResponse | JSONResponse:
    """Accept a PDF upload and enqueue it for conversion."""
    pdf_bytes = await file.read()
    
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    
    # duplicate detection
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
        job_id = app.state.job_manager.enqueue(pdf_bytes, source=file.filename)
    except asyncio.QueueFull:
        return JSONResponse(
            status_code=503,
            content={"detail": "Job queue is full. Please try again later."},
        )
        
    return JobResponse(job_id=job_id, status=JobStatus.QUEUED)


@app.get("/result/{job_id}", response_model=JobResponse)
async def get_result(job_id: str) -> JobResponse:
    """Return the current status of a conversion job."""
    job = app.state.job_manager.get_job(job_id)
    
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    
    return JobResponse(
        job_id=job.job_id,
        status=job.status,
        error=job.error,
    )


@app.get("/document/{job_id}", response_model=Document)
async def get_document(job_id: str) -> Document:
    """Retrieve the extracted document by job ID."""
    async with async_session() as session:
        document = await repository.get_by_job_id(session, job_id)
    
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    
    return document


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Liveness probe endpoint."""
    return {"status": "ok"}