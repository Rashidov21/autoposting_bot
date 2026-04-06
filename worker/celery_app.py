from __future__ import annotations

from datetime import timedelta

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "autopost",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Uzoq MTProto vazifalar: boshqa workerlar bloklanmasin
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)

celery_app.conf.task_annotations = {
    "worker.tasks.process_campaign": {
        "soft_time_limit": settings.campaign_soft_time_limit_seconds,
        "time_limit": settings.campaign_time_limit_seconds,
    },
}

celery_app.conf.beat_schedule = {
    "schedule-due-campaigns": {
        "task": "worker.tasks.schedule_due_campaigns",
        "schedule": timedelta(seconds=30),
    },
    "purge-expired-demo-users": {
        "task": "worker.tasks.purge_expired_demo_users_task",
        "schedule": timedelta(hours=1),
    },
    "subscription-reminders": {
        "task": "worker.tasks.subscription_reminder_task",
        "schedule": crontab(hour=8, minute=0),
    },
}

import worker.tasks  # noqa: E402,F401
