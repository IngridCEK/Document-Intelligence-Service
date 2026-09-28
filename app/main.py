import os
from typing import List
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import engine, Base, get_db
from app.db.models import DocumentJob, JobStatus
from app.api.endpoints import router as documents_router

# Crear tablas en PostgreSQL si no existen al arrancar
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Document Intelligence Service con procesamiento asíncrono y patrón Claim-Check"
)

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# PART 1: ingesta (POST /api/v1/documents/upload)
app.include_router(documents_router, prefix="/api/v1")


@app.on_event("startup")
def startup_event():
    """Asegura que el directorio de almacenamiento exista al iniciar."""
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)


@app.get("/")
def read_root():
    return {
        "service": settings.PROJECT_NAME,
        "status": "online",
        "docs_url": "/docs"
    }


# ==========================================
# PART 2: JOB TRACKING & RESULTS
# ==========================================

def _get_job_or_404(job_id: str, db: Session) -> DocumentJob:
    job = db.query(DocumentJob).filter(DocumentJob.id == job_id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trabajo con ID {job_id} no encontrado."
        )
    return job


@app.get("/api/v1/jobs/{job_id}")
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    """Permite consultar el estado actual del procesamiento de un documento."""
    job = _get_job_or_404(job_id, db)
    return {
        "job_id": job.id,
        "filename": job.filename,
        "file_type": job.file_type,
        "file_size_bytes": job.file_size_bytes,
        "file_hash": job.file_hash,
        "status": job.status.value,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "retry_count": job.retry_count,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at
    }


@app.get("/api/v1/jobs/{job_id}/result")
def get_job_result(job_id: str, db: Session = Depends(get_db)):
    """Obtiene el texto plano extraído y los metadatos del documento procesado."""
    job = _get_job_or_404(job_id, db)

    if job.status in (JobStatus.QUEUED, JobStatus.PROCESSING):
        return {
            "job_id": job.id,
            "status": job.status.value,
            "message": "El archivo aún se está procesando. Reintenta más tarde."
        }

    if job.status == JobStatus.FAILED:
        return {
            "job_id": job.id,
            "status": job.status.value,
            "error_code": job.error_code,
            "error_message": job.error_message
        }

    return {
        "job_id": job.id,
        "status": job.status.value,
        "extracted_text": job.extracted_text,
        "metadata": job.metadata_json,
        "completed_at": job.completed_at
    }


@app.get("/api/v1/jobs", response_model=List[dict])
def list_recent_jobs(limit: int = 20, db: Session = Depends(get_db)):
    """Lista los trabajos más recientes ordenados por fecha de creación."""
    jobs = db.query(DocumentJob).order_by(DocumentJob.created_at.desc()).limit(limit).all()
    return [
        {
            "job_id": j.id,
            "filename": j.filename,
            "file_type": j.file_type,
            "status": j.status.value,
            "created_at": j.created_at
        }
        for j in jobs
    ]
