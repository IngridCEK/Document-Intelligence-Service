import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Document Intelligence Service"
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        "postgresql://doc_user:doc_password@postgres:5432/doc_db"
    )
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "/app/uploads")
    MAX_FILE_SIZE_MB: int = 15

    class Config:
        env_file = ".env"

settings = Settings()