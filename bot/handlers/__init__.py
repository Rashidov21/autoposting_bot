from __future__ import annotations

from aiogram import Router

from bot.handlers import admin, campaign, login, payment, user


def build_router() -> Router:
    r = Router()
    r.include_router(admin.router)
    r.include_router(payment.router)
    r.include_router(campaign.router)
    r.include_router(login.router)
    r.include_router(user.router)
    return r


router = build_router()
