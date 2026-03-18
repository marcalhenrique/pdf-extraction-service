import asyncio
import structlog

from fastapi import FastAPI
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from src.config import get_settings
from src.converter import PDFConverter
from src.worker import JobManager
from src.storage import MDStorage

settings = get_settings()
logger = structlog.get_logger(__name__)


@asynccontextmanager    
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: load models, warmup, and start background workers."""
    
    # load models
    converter = PDFConverter(torch_device=settings.torch_device)
    storage = await asyncio.to_thread(MDStorage)
    
    # warmup
    try:
        warmup_bytes = Path("static/warmup.pdf").read_bytes()
        await asyncio.to_thread(converter.convert, warmup_bytes, "warmup", "warmup")
        logger.info("warmup_completed", torch_device=settings.torch_device)
    except Exception as e:
        logger.warning("warmup_failed", error=str(e))
    
    job_manager = JobManager()
    app.state.job_manager = job_manager
    app.state.storage = storage
    
    worker_task = asyncio.create_task(job_manager.process_queue(converter, storage))
    cleanup_task = asyncio.create_task(job_manager.cleanup_old_jobs())
    logger.info("worker_tasks_started")
    yield
    
    worker_task.cancel()
    cleanup_task.cancel()
    logger.info("worker_tasks_cancelled")

app = FastAPI(lifespan=_lifespan)

from src.api.routes import router  # noqa: E402
app.include_router(router)
