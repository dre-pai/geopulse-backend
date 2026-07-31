from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "geopulse",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "ingest-gdelt-every-interval": {
            "task": "app.workers.tasks.ingest_gdelt_task",
            "schedule": crontab(minute=f"*/{settings.gdelt_fetch_interval_minutes}"),
        },
        "recompute-risk-hourly": {
            "task": "app.workers.tasks.recompute_hot_risk_scores",
            "schedule": crontab(minute=10),
        },
    },
)


@worker_ready.connect
def _ingest_on_worker_ready(**_kwargs) -> None:
    """Ensure the live map has events immediately after boot, not only on the crontab."""
    celery_app.send_task("app.workers.tasks.ingest_gdelt_task")
