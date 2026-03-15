from __future__ import annotations

import asyncio
import datetime
import structlog
import time

from uuid import uuid4
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import async_sessionmaker
from src.config import get_settings
from src.schemas import JobStatus, Document
from src.converter import PDFConverter
from src.db.database import async_session
from src.db.repository import save

settings = get_settings()
logger = structlog.get_logger(__name__)

@dataclass
class Job:
    """Internal representation of a queued conversion job."""

    job_id: str
    pdf_bytes: bytes
    source: str
    status: JobStatus
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    result: asyncio.Future = field(default_factory=lambda: asyncio.get_event_loop().create_future())
    error: str | None = None

class JobManager():
    """Manages the job queue, processing pipeline, and job lifecycle."""

    def __init__(self) -> None:
        """Initialize queue, job store, and database session factory."""
        self._queue: asyncio.Queue[Job] = asyncio.Queue(maxsize=settings.queue_maxsize)
        self._jobs: dict[str, Job] = {}
        self._session: async_sessionmaker = async_session
        
    def enqueue(self, pdf_bytes: bytes, source: str) -> str:
        """Create a job and add it to the processing queue."""
        job_id = uuid4().hex[:12]
        job = Job(
            job_id=job_id,
            pdf_bytes=pdf_bytes,
            source=source,
            status=JobStatus.QUEUED,
        )
        
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull as e:
            raise asyncio.QueueFull("Job queue is full.") from e
        
        
        self._jobs[job_id] = job
        logger.info("job_enqueued", job_id=job_id, source=source, queue_size=self._queue.qsize())
        return job_id
    
    
    def get_job(self, job_id: str) -> Job | None:
        """Return a job by its ID, or None if not found."""
        return self._jobs.get(job_id)
    
    async def process_queue(self, converter: PDFConverter) -> None:
        """Continuously process jobs from the queue."""
        logger.info("worker_started") 
        while True:
            job = await self._queue.get()
            job.status = JobStatus.PROCESSING
            logger.info("job_processing_started", job_id=job.job_id, source=job.source)
            
            try:
                time_start = time.perf_counter()
                document = await asyncio.to_thread(converter.convert, job.pdf_bytes, job.source, job.job_id)
                time_end = time.perf_counter()
                
                job.status = JobStatus.DONE
                processing_time_ms = int((time_end - time_start) * 1000)
                document.processing_time_ms = processing_time_ms
                document.processed_at = datetime.datetime.now()
                
                async with self._session() as session:
                    await save(session, document)
                    
                logger.info("job_done", job_id=job.job_id)
                if not job.result.done():
                    job.result.set_result(document)
            except Exception as e:
                job.error = str(e)
                job.status = JobStatus.ERROR
                logger.error("job_error", job_id=job.job_id, error=str(e))
                if not job.result.done():
                    job.result.set_exception(e)
            finally:
                job.pdf_bytes = b""
                self._queue.task_done()
    
    async def cleanup_old_jobs(self) -> None:
        """Periodically remove expired jobs from memory."""
        while True:
            await asyncio.sleep(300)
            cutoff = datetime.datetime.now().timestamp() - settings.job_ttl_minutes * 60
            removed = self._remove_expired_jobs(cutoff)
            if removed:
                logger.info("old_jobs_removed", count=removed)
    
    def _remove_expired_jobs(self, cutoff: float) -> int:
        """Delete jobs past the cutoff timestamp and return the count removed."""
        expired = [
            job_id for job_id, job in list(self._jobs.items())
            if job.status in (JobStatus.DONE, JobStatus.ERROR)
            and job.created_at.timestamp() < cutoff
        ]
        for job_id in expired:
            del self._jobs[job_id]
        return len(expired)