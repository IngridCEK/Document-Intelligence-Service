from datetime import datetime, timedelta
from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.db.models import DocumentJob, JobStatus
from app.tasks.worker import process_document_task


# El nombre explícito debe coincidir con el de beat_schedule en core/celery_app.py
@celery_app.task(name="app.tasks.cleanup_stale_jobs")
def cleanup_stale_jobs():
    """Tarea periódica (Beat) para limpiar o re-encolar trabajos atascados."""
    db = SessionLocal()
    try:
        # Jobs en QUEUED por más de 5 min -> re-encolar
        stale_queued_time = datetime.utcnow() - timedelta(minutes=5)
        stale_queued = db.query(DocumentJob).filter(
            DocumentJob.status == JobStatus.QUEUED,
            DocumentJob.created_at < stale_queued_time
        ).all()
        for j in stale_queued:
            process_document_task.delay(j.id)

        # Jobs en PROCESSING por más de 10 min -> marcar como FAILED
        stale_processing_time = datetime.utcnow() - timedelta(minutes=10)
        stale_processing = db.query(DocumentJob).filter(
            DocumentJob.status == JobStatus.PROCESSING,
            DocumentJob.updated_at < stale_processing_time
        ).all()
        for j in stale_processing:
            j.status = JobStatus.FAILED
            j.error_code = "WORKER_CRASH_OR_TIMEOUT"
            j.error_message = "El trabajo expiró en estado PROCESSING sin respuesta del worker."
            j.completed_at = datetime.utcnow()
            j.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()
