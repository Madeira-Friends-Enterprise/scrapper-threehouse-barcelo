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

# Barceló's Portugal country page. If it moves we fall back to the global
# search endpoint with a country filter.
PT_LANDING_URLS = [
    "https://www.barcelo.com/pt-pt/hoteis/europa/portugal/",
    "https://www.barcelo.com/pt-pt/hotels/europa/portugal/",
    "https://www.barcelo.com/pt-pt/hoteles/europa/portugal/",
]

HOTEL_PAGE = "https://www.barcelo.com/pt-pt/{slug}/"
CACHE_TTL_SECONDS = 7 * 24 * 3600

UTAG_HOTEL_ID_RE = re.compile(r'"hotel_id"\s*:\s*"?(\d+)"?')
UTAG_CITY_RE = re.compile(r'"hotel_city"\s*:\s*"([^"]+)"')
UTAG_NAME_RE = re.compile(r'"hotel_name"\s*:\s*"([^"]+)"')


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


def _extract_slugs(html: str) -> list[str]:
    """Pull hotel slugs from anchor hrefs on the Portugal landing page."""
    slugs = set()
    for m in re.finditer(r'href="(?:https://www\.barcelo\.com)?/pt-pt/([a-z0-9][a-z0-9-]+)/"', html):
        slug = m.group(1)
        # Filter out navigation / category slugs
        if slug in {"hoteis", "hotels", "hoteles", "europa", "portugal", "ofertas",
                    "experiencias", "my-barcelo", "barcelo-hotel-group", "destinos"}:
            continue
        if "-" not in slug:
            continue
        slugs.add(slug)
    return sorted(slugs)


def _extract_utag(html: str) -> tuple[str | None, str | None, str | None]:
    hotel_id = UTAG_HOTEL_ID_RE.search(html)
    city = UTAG_CITY_RE.search(html)
    name = UTAG_NAME_RE.search(html)
    return (
        hotel_id.group(1) if hotel_id else None,
        city.group(1) if city else None,
        name.group(1) if name else None,
    )


def discover_barcelo_portugal(ctx: BrowserContext, cache_path: Path, force: bool = False) -> list[BarceloHotel]:
    if not force:
        cached = _load_cache(cache_path)
        if cached:
            log.info("barcelo: using cached hotel list (%d entries)", len(cached))
            return cached

    page = ctx.new_page()
    html = ""
    for url in PT_LANDING_URLS:
        try:
            resp = page.goto(url, wait_until="domcontentloaded")
            if resp and resp.ok:
                page.wait_for_timeout(1500)
                html = page.content()
                log.info("barcelo: landing page OK at %s", url)
                break
        except Exception as exc:
            log.debug("barcelo: landing %s failed: %s", url, exc)

    slugs: list[str] = []
    if html:
        slugs = _extract_slugs(html)

    # Safety net: if the landing page failed or yielded nothing, seed with
    # hotels known to exist in Portugal so the scraper still produces output.
    fallback_slugs = [
        "barcelo-aguamarina",
        "occidental-lisboa-marques-de-pombal",
        "occidental-praia-de-oura",
        "occidental-praia-da-luz",
        "occidental-lisboa-5th-avenue",
    ]
    if not slugs:
        log.warning("barcelo: no slugs parsed from landing, using fallback list")
        slugs = fallback_slugs
    else:
        slugs = sorted(set(slugs) | set(fallback_slugs))

    hotels: list[BarceloHotel] = []
    for slug in slugs:
        url = HOTEL_PAGE.format(slug=slug)
        try:
            resp = page.goto(url, wait_until="domcontentloaded")
        except Exception as exc:
            log.debug("barcelo: %s unreachable (%s)", slug, exc)
            continue
        if not resp or not resp.ok:
            continue
        page.wait_for_timeout(600)
        body = page.content()
        hotel_id, city, name = _extract_utag(body)
        if not hotel_id:
            continue
        # Keep only Portugal hotels. utag exposes hotel_country in many deployments.
        country_match = re.search(r'"hotel_country"\s*:\s*"([^"]+)"', body)
        if country_match and "portugal" not in country_match.group(1).lower():
            continue
        hotels.append(
            BarceloHotel(
                slug=slug,
                name=name or slug.replace("-", " ").title(),
                city=city or "",
                hotel_id=hotel_id,
            )
        )

    page.close()
    _save_cache(cache_path, hotels)
    log.info("barcelo: discovered %d Portugal hotels", len(hotels))
    return hotels
