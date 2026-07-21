import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Load the Celery app on Django startup. Without this the web process publishes
# tasks with Celery's built-in defaults — ignoring task_routes in config/celery.py
# — so queued work lands in the "celery" queue instead of "ai"/"sync"/"broadcast".
from .celery import app as celery_app  # noqa: E402

__all__ = ("celery_app",)
