from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from playwright.sync_api import BrowserContext

log = logging.getLogger(__name__)

# Only target hotel: Barceló Funchal Oldtown.
TARGET_SLUG = "barcelo-funchal-oldtown"
TARGET_NAME = "Barceló Funchal Oldtown"
TARGET_CITY = "Funchal"

HOTEL_PAGE = "https://www.barcelo.com/pt-pt/{slug}/"
CACHE_TTL_SECONDS = 7 * 24 * 3600

ID_PATTERNS = [
    re.compile(r'"hotel_id"\s*:\s*"?(\d+)"?'),
    re.compile(r'"hotelId"\s*:\s*"?(\d+)"?'),
    re.compile(r'data-hotel-id="(\d+)"'),
    re.compile(r'hotelId=(\d+)'),
    re.compile(r'/hotels/(\d+)/availability'),
    re.compile(r'"id"\s*:\s*"(\d{5,8})"'),
]


@dataclass
class BarceloHotel:
    slug: str
    name: str
    city: str
    hotel_id: str

    @property
    def page_url(self) -> str:
        return HOTEL_PAGE.format(slug=self.slug)


def _load_cache(path: Path) -> list[BarceloHotel] | None:
    if not path.exists():
        return None
    age = time.time() - path.stat().st_mtime
    if age > CACHE_TTL_SECONDS:
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [BarceloHotel(**h) for h in raw]
    except Exception as exc:
        log.warning("barcelo cache unreadable (%s), rediscovering", exc)
        return None


def _save_cache(path: Path, hotels: Iterable[BarceloHotel]) -> None:
    path.write_text(
        json.dumps([asdict(h) for h in hotels], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _extract_hotel_id(html: str) -> str | None:
    for pat in ID_PATTERNS:
        m = pat.search(html)
        if m:
            return m.group(1)
    return None


def discover_barcelo_portugal(ctx: BrowserContext, cache_path: Path, force: bool = False) -> list[BarceloHotel]:
    """Discover the single target hotel (Barceló Funchal Oldtown)."""
    if not force:
        cached = _load_cache(cache_path)
        if cached:
            log.info("barcelo: using cached hotel (%s)", cached[0].slug)
            return cached

    page = ctx.new_page()
    url = HOTEL_PAGE.format(slug=TARGET_SLUG)
    log.info("barcelo: opening %s", url)

    hotel_id: str | None = None

    # Capture network responses — the availability API URL contains the hotel_id.
    def on_response(resp):
        nonlocal hotel_id
        if hotel_id:
            return
        m = re.search(r'/hotels/(\d+)/availability', resp.url)
        if m:
            hotel_id = m.group(1)
            log.info("barcelo: hotel_id from network = %s", hotel_id)

    page.on("response", on_response)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
    except Exception as exc:
        log.warning("barcelo: page load issue (%s), continuing with what we have", exc)

    if not hotel_id:
        try:
            html = page.content()
            if "Access Denied" in html[:500]:
                log.error("barcelo: Akamai blocked the request (Access Denied)")
            hotel_id = _extract_hotel_id(html)
            if hotel_id:
                log.info("barcelo: hotel_id from HTML = %s", hotel_id)
        except Exception as exc:
            log.warning("barcelo: could not read content (%s)", exc)

    page.close()

    if not hotel_id:
        log.error("barcelo: could not discover hotel_id for %s", TARGET_SLUG)
        return []

    hotel = BarceloHotel(
        slug=TARGET_SLUG,
        name=TARGET_NAME,
        city=TARGET_CITY,
        hotel_id=hotel_id,
    )
    _save_cache(cache_path, [hotel])
    log.info("barcelo: discovered 1 hotel (%s, id=%s)", hotel.slug, hotel.hotel_id)
    return [hotel]
