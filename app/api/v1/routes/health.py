from __future__ import annotations

import redis
from fastapi import APIRouter, Response, status

from app.core.config import get_settings
from app.db.session import check_db_connection

router = APIRouter()


@router.get("/health")
def health_compat() -> dict:
    """Eski klientlar va oddiy probe uchun."""
    return {"status": "ok"}


@router.get("/health/live")
def liveness() -> dict:
    """Jarayon ishlayaptimi (DB/Redis tekshirilmaydi)."""
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(response: Response) -> dict:
    """PostgreSQL va Redis mavjudligi."""
    try:
        check_db_connection()
    except Exception as exc:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unready", "detail": "database", "error": str(exc)[:200]}

    try:
        s = get_settings()
        r = redis.from_url(s.redis_url, socket_connect_timeout=2)
        r.ping()
    except Exception as exc:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unready", "detail": "redis", "error": str(exc)[:200]}

    return {"status": "ready"}
