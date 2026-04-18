from __future__ import annotations

from datetime import timedelta

from celery import Celery
from celery.schedules import crontab
from kombu import Queue

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
    task_ignore_result=settings.celery_task_ignore_result,
    result_expires=settings.celery_result_expires_seconds,
    task_default_queue=settings.celery_default_queue,
    task_queues=(
        Queue(settings.celery_default_queue),
        Queue(settings.celery_campaign_queue),
        Queue(settings.celery_scheduler_queue),
    ),
    task_routes={
        "worker.tasks.process_campaign": {"queue": settings.celery_campaign_queue},
        "worker.tasks.schedule_due_campaigns": {"queue": settings.celery_scheduler_queue},
        "worker.tasks.purge_expired_demo_users_task": {"queue": settings.celery_scheduler_queue},
        "worker.tasks.subscription_reminder_task": {"queue": settings.celery_scheduler_queue},
        "worker.tasks.prune_send_logs_task": {"queue": settings.celery_scheduler_queue},
    },
    # Uzoq MTProto vazifalar: boshqa workerlar bloklanmasin
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=settings.celery_worker_prefetch_multiplier,
    worker_max_tasks_per_child=settings.celery_worker_max_tasks_per_child,
    worker_max_memory_per_child=settings.celery_worker_max_memory_per_child_kb,
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
        "options": {"queue": settings.celery_scheduler_queue},
    },
    "purge-expired-demo-users": {
        "task": "worker.tasks.purge_expired_demo_users_task",
        "schedule": timedelta(hours=1),
        "options": {"queue": settings.celery_scheduler_queue},
    },
    "subscription-reminders": {
        "task": "worker.tasks.subscription_reminder_task",
        "schedule": crontab(hour=8, minute=0),
        "options": {"queue": settings.celery_scheduler_queue},
    },
    "prune-send-logs": {
        "task": "worker.tasks.prune_send_logs_task",
        "schedule": crontab(hour=3, minute=0),
        "options": {"queue": settings.celery_scheduler_queue},
    },
}

import worker.tasks  # noqa: E402,F401
