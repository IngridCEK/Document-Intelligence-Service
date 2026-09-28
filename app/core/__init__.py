"""
Módulo core de la aplicación.
Importa la instancia de Celery para facilitar su uso en la aplicación.
"""

from .celery_app import celery_app

__all__ = ("celery_app",)