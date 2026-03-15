import logging
import uvicorn

from src.config import get_settings
from src.logging import configure_logging
from src.api import app

settings = get_settings()
configure_logging(
    console_level=getattr(logging, settings.log_level.upper(), logging.DEBUG),
)
logger = logging.getLogger(__name__)

def main() -> None:
    """Start the Uvicorn server with configured host and port."""
    uvicorn.run(app, host=settings.host, port=settings.port)

if __name__ == "__main__":
    main()