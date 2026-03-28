from __future__ import annotations

import socks

from app.core.security import decrypt_text
from app.db.models import Proxy


def proxy_tuple(p: Proxy) -> tuple:
    t = (p.proxy_type or "").lower()
    pwd: str | None = None
    if p.password_enc:
        pwd = decrypt_text(p.password_enc)

    if t == "mtproxy":
        if not p.secret:
            raise ValueError("MTProxy secret kerak")
        return ("mtproxy", p.host, p.port, p.secret)

    if t == "socks5":
        if p.username and pwd:
            return (socks.SOCKS5, p.host, p.port, True, p.username, pwd)
        return (socks.SOCKS5, p.host, p.port)

    if t == "http":
        if p.username and pwd:
            return (socks.HTTP, p.host, p.port, True, p.username, pwd)
        return (socks.HTTP, p.host, p.port)

    raise ValueError(f"Noma'lum proxy turi: {p.proxy_type}")
