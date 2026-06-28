from celery import Celery
from app.config import settings

# No result backend needed — tasks use ignore_result=True for fire-and-forget
celery_app = Celery(
    "alfaleus",
    broker=settings.REDIS_URL,
    include=["app.pipeline.orchestrator"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)
