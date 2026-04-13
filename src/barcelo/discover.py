from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from curl_cffi import requests as cffi
from playwright.sync_api import BrowserContext

log = logging.getLogger(__name__)

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
]

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


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


def _fetch_with_cffi(url: str) -> str | None:
    """Try curl_cffi with Chrome120 TLS impersonation — beats Akamai's TLS fingerprinting."""
    for impersonate in ("chrome124", "chrome120", "chrome110"):
        try:
            r = cffi.get(url, headers=BROWSER_HEADERS, impersonate=impersonate, timeout=30)
            if r.status_code == 200 and "Access Denied" not in r.text[:1000]:
                log.info("barcelo: cffi/%s OK (%d bytes)", impersonate, len(r.text))
                return r.text
            log.warning(
                "barcelo: cffi/%s status=%s denied=%s",
                impersonate, r.status_code, "Access Denied" in r.text[:1000],
            )
        except Exception as exc:
            log.warning("barcelo: cffi/%s error: %s", impersonate, exc)
    return None


def _fetch_with_playwright(ctx: BrowserContext, url: str) -> str | None:
    page = ctx.new_page()
    captured_id = {"v": None}

    def on_response(resp):
        if captured_id["v"]:
            return
        m = re.search(r'/hotels/(\d+)/availability', resp.url)
        if m:
            captured_id["v"] = m.group(1)

    page.on("response", on_response)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        html = page.content()
        if captured_id["v"]:
            # Bake the discovered id into the HTML so the regex picks it up.
            html = f'data-hotel-id="{captured_id["v"]}"\n' + html
        return html
    except Exception as exc:
        log.warning("barcelo: playwright load issue (%s)", exc)
        return None
    finally:
        page.close()


def discover_barcelo_portugal(ctx: BrowserContext, cache_path: Path, force: bool = False) -> list[BarceloHotel]:
    """Discover Barceló Funchal Oldtown — try curl_cffi first (TLS bypass), then Playwright."""
    if not force:
        cached = _load_cache(cache_path)
        if cached:
            log.info("barcelo: using cached hotel (%s, id=%s)", cached[0].slug, cached[0].hotel_id)
            return cached

    url = HOTEL_PAGE.format(slug=TARGET_SLUG)
    log.info("barcelo: discovering %s", url)

    html = _fetch_with_cffi(url)
    if not html:
        log.info("barcelo: cffi failed, falling back to Playwright")
        html = _fetch_with_playwright(ctx, url)

    if not html:
        log.error("barcelo: all fetch strategies failed")
        return []

    hotel_id = _extract_hotel_id(html)
    if not hotel_id:
        log.error("barcelo: no hotel_id pattern matched (HTML %d bytes)", len(html))
        # Save HTML for inspection in workflow logs
        try:
            Path("barcelo_funchal_dump.html").write_text(html, encoding="utf-8")
        except Exception:
            pass
        return []

    hotel = BarceloHotel(
        slug=TARGET_SLUG,
        name=TARGET_NAME,
        city=TARGET_CITY,
        hotel_id=hotel_id,
    )
    _save_cache(cache_path, [hotel])
    log.info("barcelo: discovered %s (id=%s)", hotel.slug, hotel.hotel_id)
    return [hotel]
