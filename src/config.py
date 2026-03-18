from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    log_level: str = "DEBUG"
    
    host: str = "0.0.0.0"
    port: int = 8503
    
    queue_maxsize: int = 50
    torch_device: str = "cuda"
    job_ttl_minutes: int = 30
    
    db_host: str = "localhost"
    db_port: int = 5431
    db_user: str = "postgres"
    db_password: str = "postgres"
    db_name: str = "pdf_extraction_db"
    
    minio_host: str = "minio"
    minio_port: int = 9000
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "pdf-extraction-service"
    minio_public_url: str = "http://minio:9000"
    
    webhook_url: str | None = None
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    @property
    def db_url(self) -> str:
        """Build the async PostgreSQL connection URL."""
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
    

@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
