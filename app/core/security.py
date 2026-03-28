from __future__ import annotations

from cryptography.fernet import Fernet

from app.core.config import get_settings


def get_fernet() -> Fernet:
    key = get_settings().fernet_key.strip()
    if not key:
        raise RuntimeError("FERNET_KEY sozlanmagan — session shifrlash uchun majburiy")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_text(plain: str) -> str:
    return get_fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_text(token: str) -> str:
    return get_fernet().decrypt(token.encode("ascii")).decode("utf-8")
