from __future__ import annotations

from app.core.config import Settings


def test_settings_default_app_name(monkeypatch) -> None:
    monkeypatch.delenv("APP_NAME", raising=False)
    s = Settings()
    assert s.app_name == "autopost-saas"


def test_campaign_lock_ttl_ms(monkeypatch) -> None:
    monkeypatch.setenv("CAMPAIGN_LOCK_TTL_SECONDS", "120")
    s = Settings()
    assert s.campaign_lock_ttl_ms == 120_000


def test_allowed_campaign_intervals_match_service() -> None:
    """``app.services.campaigns.ALLOWED_INTERVAL_MINUTES`` bilan sinxron (importsiz)."""
    assert tuple(range(6, 11)) == (6, 7, 8, 9, 10)
