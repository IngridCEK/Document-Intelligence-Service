import os
import time
from datetime import datetime

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.db.models import DocumentJob, JobStatus
from app.services.parser import (
    process_pdf, process_image, process_text_file, calculate_sha256,
    CorruptedFileError, EncryptedPDFError, UnsupportedFormatError
)

TERMINAL_STATES = (JobStatus.COMPLETED, JobStatus.FAILED)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def process_document_task(self, job_id: str):
    db = SessionLocal()
    job = db.query(DocumentJob).filter(DocumentJob.id == job_id).first()
    if not job:
        db.close()
        return

    # Mensaje duplicado o reentregado de un job que ya terminó: no hay nada que hacer.
    if job.status in TERMINAL_STATES:
        db.close()
        return

    start_time = time.time()
    job.status = JobStatus.PROCESSING
    job.updated_at = datetime.utcnow()
    db.commit()

    try:
        file_path = job.file_path
        if not os.path.exists(file_path):
            raise CorruptedFileError("El archivo asignado no existe en el disco.")

        sha256 = calculate_sha256(file_path)

        # Verificar duplicados
        duplicate_job = db.query(DocumentJob).filter(
            DocumentJob.file_hash == sha256,
            DocumentJob.id != job_id,
            DocumentJob.status == JobStatus.COMPLETED
        ).first()

        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".pdf":
            text, meta = process_pdf(file_path)
        elif ext in [".png", ".jpg", ".jpeg"]:
            text, meta = process_image(file_path)
        elif ext == ".txt":
            text, meta = process_text_file(file_path)
        else:
            raise UnsupportedFormatError(f"Formato extensión {ext} no soportado.")

        elapsed = round(time.time() - start_time, 4)
        meta["processing_time_seconds"] = elapsed
        meta["sha256_hash"] = sha256
        if duplicate_job:
            meta["duplicate_of_job_id"] = duplicate_job.id

        job.status = JobStatus.COMPLETED
        job.extracted_text = text
        job.file_hash = sha256
        job.metadata_json = meta
        job.error_code = None
        job.error_message = None
        job.completed_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        db.commit()

    except (CorruptedFileError, EncryptedPDFError, UnsupportedFormatError) as err:
        # Errores fatales: NO REINTENTAR
        job.status = JobStatus.FAILED
        job.error_code = err.__class__.__name__
        job.error_message = str(err)
        job.completed_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        db.commit()

    except Exception as exc:
        job.retry_count = self.request.retries + 1
        if self.request.retries < self.max_retries:
            job.error_message = f"Error temporal: {str(exc)}. Reintentando ({job.retry_count}/{self.max_retries})..."
            db.commit()
            db.close()
            raise self.retry(exc=exc)
        else:
            job.status = JobStatus.FAILED
            job.error_code = "MAX_RETRIES_EXCEEDED"
            job.error_message = f"Error tras {self.max_retries} reintentos: {str(exc)}"
            job.completed_at = datetime.utcnow()
            job.updated_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()
