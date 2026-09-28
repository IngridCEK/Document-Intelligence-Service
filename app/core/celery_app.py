import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# `include` garantiza que el worker importe los módulos con las tareas
# (así Flower y Beat no necesitan cargar el parser ni la BD para arrancar).
celery_app = Celery(
    "doc_intel",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.tasks.worker", "app.tasks.cleanup"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_transport_options={
        "visibility_timeout": 120  # 2 minutos para reentregar si el worker muere con kill -9
    },
    task_time_limit=300,        # Termina la tarea si tarda más de 5 minutos (evita colgados eternos)
    task_soft_time_limit=240,   # Soft limit
    beat_schedule={
        "cleanup-stale-jobs-every-2-minutes": {
            "task": "app.tasks.cleanup_stale_jobs",
            "schedule": 120.0,
        },
    },
)
