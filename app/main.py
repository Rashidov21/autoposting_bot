from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api.v1.router import router as api_v1_router
from app.core.config import get_settings
from app.db.session import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)
app.include_router(api_v1_router, prefix="/api/v1")


@app.get("/health")
def root_health() -> dict:
    return {"status": "ok"}


@app.on_event("startup")
def _startup() -> None:
    init_db()
    logger.info("DB metadata yuklandi (create_all)")
