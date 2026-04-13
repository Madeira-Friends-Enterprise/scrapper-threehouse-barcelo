from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(key: str, default: str | None = None) -> str:
    value = os.getenv(key, default)
    if value is None:
        raise RuntimeError(f"Missing env var: {key}")
    return value


@dataclass(frozen=True)
class Settings:
    sheet_id: str
    sheet_gid: int
    service_account_path: Path
    end_date: date
    headless: bool
    browser_timeout_ms: int
    barcelo_cache_path: Path

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            sheet_id=_env("GOOGLE_SHEET_ID", "1HPyd0LnqI7c1eKKY4gGQcQ__ct0hnVZxkUaOeEYAJKY"),
            sheet_gid=int(_env("GOOGLE_SHEET_GID", "1379799510")),
            service_account_path=ROOT / _env("GOOGLE_SERVICE_ACCOUNT_JSON", "credentials/service_account.json"),
            end_date=date.fromisoformat(_env("SCRAPE_END_DATE", "2026-12-31")),
            headless=_env("HEADLESS", "true").lower() == "true",
            browser_timeout_ms=int(_env("BROWSER_TIMEOUT_MS", "45000")),
            barcelo_cache_path=ROOT / "barcelo_hotels.json",
        )
