import enum
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Enum, Text, Integer, JSON
from app.db.session import Base


class JobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DocumentJob(Base):
    __tablename__ = "document_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    file_hash = Column(String(64), nullable=True, index=True)  # SHA-256 (detección de duplicados)

    status = Column(Enum(JobStatus), default=JobStatus.QUEUED, nullable=False)
    error_code = Column(String(64), nullable=True)   # p. ej. CorruptedFileError, MAX_RETRIES_EXCEEDED
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)

    # Resultado del procesamiento
    extracted_text = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=True)

    # Timestamps para monitoreo y auditoría
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
