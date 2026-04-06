from __future__ import annotations

from aiogram import Router

from bot.handlers import admin, campaign, login, payment, user


def build_router() -> Router:
    r = Router()
    # user birinchi — bosh menyudagi tugmalar (masalan Qo'llanma) FSM dan oldin ishlashi uchun
    r.include_router(user.router)
    r.include_router(login.router)
    r.include_router(payment.router)
    r.include_router(campaign.router)
    r.include_router(admin.router)
    return r


router = build_router()
