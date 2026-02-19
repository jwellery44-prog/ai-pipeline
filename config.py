import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Supabase
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str
    
    # AI Models
    REVE_API_KEY: str
    REVE_PROMPT: str = ""
    NANOBANA_API_KEY: str
    NANOBANA_PROMPT: str = ""
    
    # App Config
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    
    # Worker Config
    POLL_INTERVAL_SECONDS: int = 2
    MAX_CONCURRENT_JOBS: int = 5
    MAX_RETRIES: int = 3
    PROCESSING_TIMEOUT_SECONDS: int = 300
    
    # Storage Config
    RAW_BUCKET_NAME: str = "raw_images"
    PROCESSED_BUCKET_NAME: str = "processed_images"
    ALLOWED_MIME_TYPES: list[str] = ["image/jpeg", "image/png", "image/webp"]
    MAX_FILE_SIZE_BYTES: int = 10 * 1024 * 1024  # 10MB

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
