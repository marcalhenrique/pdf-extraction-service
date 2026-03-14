from logging import getLogger
from src.config import get_settings
from src.logging import configure_logging

settings = get_settings()
configure_logging(
    console_level=settings.console_log_level,
)
logger = getLogger(__name__)

def main():
    pass

if __name__ == "__main__":
    main()