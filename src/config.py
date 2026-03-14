import os
import time
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    
    log_level: str = "DEBUG"
    timezone: str = "UTC"
    
    host: str = "0.0.0.0"
    port: int = 8503
    
    queue_maxsize: int = 50
    torch_device: str = "cuda"
    job_ttl_minutes: int = 30
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

@lru_cache()
def get_settings() -> Settings:
    settings = Settings()
    try:
        if settings.timezone:
            os.environ["TZ"] = settings.timezone
            time.tzset()
    except Exception as e:
        pass
    os.environ["TORCH_DEVICE"] = settings.torch_device
    return settings
    