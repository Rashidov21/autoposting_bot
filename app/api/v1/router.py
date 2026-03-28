from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes import admin, analytics, campaigns, health, users

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(users.router, prefix="/users", tags=["users"])
router.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
router.include_router(admin.router, prefix="/admin", tags=["admin"])
