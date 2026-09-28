import logging
import os
import uuid

import magic
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.db.models import DocumentJob, JobStatus
from app.tasks.worker import process_document_task

logger = logging.getLogger(__name__)
router = APIRouter()

# Tipo MIME detectado por CONTENIDO (no por extensión) -> extensión con la que se guarda
ALLOWED_MIME_TYPES = {
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpg",
}


@router.post("/documents/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    filename = (file.filename or "sin_nombre")[:255]
    original_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    # 1. Validación por contenido real con python-magic (no basta con la extensión)
    header = await file.read(2048)
    if not header:
        raise HTTPException(status_code=400, detail="El archivo subido está vacío (0 bytes).")

    mime = magic.from_buffer(header, mime=True)
    if mime in ALLOWED_MIME_TYPES:
        ext = ALLOWED_MIME_TYPES[mime]
    elif mime.startswith("text/") and original_ext == "txt":
        ext = "txt"
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de archivo no soportado (detectado: '{mime}'). Formatos permitidos: PDF, PNG, JPG, TXT."
        )

    # 2. Guardado con nombre sanitizado {job_id}.{ext} y control de tamaño acumulado
    job_id = str(uuid.uuid4())
    upload_dir = settings.UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)
    saved_path = os.path.join(upload_dir, f"{job_id}.{ext}")

    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    total_written = len(header)
    too_big = False
    with open(saved_path, "wb") as f:
        f.write(header)
        while chunk := await file.read(1024 * 1024):  # chunks de 1 MB
            total_written += len(chunk)
            if total_written > max_bytes:
                too_big = True
                break
            f.write(chunk)

    if too_big:
        os.remove(saved_path)
        raise HTTPException(
            status_code=400,
            detail=f"El archivo excede el límite máximo permitido de {settings.MAX_FILE_SIZE_MB} MB."
        )

    # 3. Registrar el job en la BD (claim-check: el archivo queda en disco, la cola solo lleva el id)
    job = DocumentJob(
        id=job_id,
        filename=filename,
        file_path=saved_path,
        file_type=ext,
        file_size_bytes=total_written,
        status=JobStatus.QUEUED,
        retry_count=0,
    )
    db.add(job)
    db.commit()

    # 4. Encolar. Si Redis no responde, el job ya está guardado y el reaper (Beat) lo re-encolará.
    try:
        process_document_task.delay(job_id)
        message = "Archivo aceptado y enviado a la cola de procesamiento."
    except Exception as exc:
        logger.error("No se pudo encolar el job %s: %s", job_id, exc)
        message = "Archivo guardado, pero la cola no está disponible en este momento; se reintentará automáticamente."

    return {
        "job_id": job_id,
        "filename": filename,
        "status": JobStatus.QUEUED.value,
        "size_bytes": total_written,
        "message": message,
    }
