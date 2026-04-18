from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from app.core.config import get_settings


def verify_internal_secret(x_internal_secret: str | None = Header(default=None)) -> None:
    expected = get_settings().internal_api_secret
    if not x_internal_secret or not hmac.compare_digest(x_internal_secret, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
