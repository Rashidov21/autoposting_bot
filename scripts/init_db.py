"""
Jadval yaratish (dev). Ishlatish: loyiha ildizidan
  python -m scripts.init_db
"""
from __future__ import annotations

from app.db.session import init_db


def main() -> None:
    init_db()
    print("OK: metadata yaratildi (Alembic productionda tavsiya etiladi).")


if __name__ == "__main__":
    main()
