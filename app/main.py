from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.api.v1.router import router as api_v1_router
from app.core.config import get_settings
from app.db.session import check_db_connection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    try:
        check_db_connection()
        logger.info("DB ulanishi tasdiqlandi")
    except Exception as exc:
        logger.warning("DB ulanishi tekshirilmadi: %s", exc)
    yield


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
app.include_router(api_v1_router, prefix="/api/v1")


@app.get("/health")
def root_health() -> dict:
    return {"status": "ok"}
