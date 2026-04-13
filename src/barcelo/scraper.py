from __future__ import annotations

import json
import logging
import re
from calendar import monthrange
from datetime import date, timedelta
from typing import Any, Iterable

from curl_cffi import requests as cffi
from playwright.sync_api import BrowserContext
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..models import PriceRow
from .discover import BarceloHotel

log = logging.getLogger(__name__)

BRAND = "Barceló"
AVAILABILITY_URL = (
    "https://reservation-api.barcelo.com/hotel-availability-adapter/v1/hotels/{id}/availability"
)


class BarceloFetchError(RuntimeError):
    pass


def _month_windows(start: date, end: date) -> list[tuple[date, date]]:
    windows: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        last = date(cur.year, cur.month, monthrange(cur.year, cur.month)[1])
        win_end = min(last, end)
        windows.append((cur, win_end))
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    return windows


def _iter_daily_prices(payload: Any) -> Iterable[tuple[date, float | None, bool]]:
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            d = (
                node.get("date")
                or node.get("day")
                or node.get("checkIn")
                or node.get("stayDate")
            )
            price_candidate = None
            for key in ("totalAmount", "amount", "price", "minPrice", "rate", "nightlyRate"):
                if key in node and node[key] is not None:
                    price_candidate = node[key]
                    break
            if isinstance(price_candidate, dict):
                price_candidate = (
                    price_candidate.get("amount")
                    or price_candidate.get("value")
                    or price_candidate.get("gross")
                )
            if isinstance(d, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d[:10]):
                try:
                    dd = date.fromisoformat(d[:10])
                    price = float(price_candidate) if price_candidate is not None else None
                    avail = bool(node.get("available", price is not None))
                    yield dd, price, avail
                    continue
                except (TypeError, ValueError):
                    pass
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def _make_session(hotel: BarceloHotel) -> cffi.Session:
    """Open a cffi session, warm it up by visiting the hotel page (gets Akamai cookies)."""
    s = cffi.Session(impersonate="chrome124")
    warmup_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
    }
    try:
        r = s.get("https://www.barcelo.com/pt-pt/", headers=warmup_headers, timeout=30)
        log.info("barcelo: session warmup root status=%s cookies=%d", r.status_code, len(s.cookies))
        r = s.get(hotel.page_url, headers=warmup_headers, timeout=30)
        log.info("barcelo: session warmup hotel status=%s cookies=%d", r.status_code, len(s.cookies))
    except Exception as exc:
        log.warning("barcelo: warmup failed (%s)", exc)
    return s


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1.5, min=2, max=15),
    retry=retry_if_exception_type(BarceloFetchError),
)
def _fetch_window_cffi(
    session: cffi.Session, hotel: BarceloHotel, check_in: date, check_out: date
) -> list[tuple[date, float | None, bool]]:
    body = {
        "checkIn": check_in.isoformat(),
        "checkOut": check_out.isoformat(),
        "adults": 2,
        "children": 0,
        "rooms": 1,
        "currency": "EUR",
        "language": "pt-PT",
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
        "Origin": "https://www.barcelo.com",
        "Referer": hotel.page_url,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36"
        ),
    }
    url = AVAILABILITY_URL.format(id=hotel.hotel_id)
    try:
        r = session.post(url, json=body, headers=headers, timeout=30)
    except Exception as exc:
        raise BarceloFetchError(f"network: {exc}") from exc

    if r.status_code >= 500 or r.status_code == 403:
        raise BarceloFetchError(f"status {r.status_code}")
    if not r.ok:
        log.debug("barcelo %s %s..%s -> %s", hotel.slug, check_in, check_out, r.status_code)
        return []
    try:
        data = r.json()
    except Exception:
        return []
    return list(_iter_daily_prices(data))


def scrape_barcelo_hotel(ctx: BrowserContext, hotel: BarceloHotel, end_date: date) -> list[PriceRow]:
    today = date.today()
    captured: dict[date, tuple[float | None, bool]] = {}
    session = _make_session(hotel)

    for win_start, win_end in _month_windows(today, end_date):
        check_out = win_end + timedelta(days=1)
        try:
            rows = _fetch_window_cffi(session, hotel, win_start, check_out)
        except BarceloFetchError as exc:
            log.warning("barcelo %s %s..%s failed: %s", hotel.slug, win_start, win_end, exc)
            continue
        for d, price, avail in rows:
            if win_start <= d <= win_end:
                captured.setdefault(d, (price, avail))

    out: list[PriceRow] = []
    d = today
    while d <= end_date:
        price, avail = captured.get(d, (None, False))
        out.append(
            PriceRow(
                brand=BRAND,
                hotel_name=hotel.name,
                hotel_id=hotel.hotel_id,
                city=hotel.city,
                date=d,
                price=price,
                available=avail and price is not None,
                source_url=hotel.page_url,
            )
        )
        d += timedelta(days=1)

    covered = sum(1 for r in out if r.price is not None)
    log.info("barcelo %s: %d rows (%d with price)", hotel.slug, len(out), covered)
    return out


def scrape_all_barcelo(ctx: BrowserContext, hotels: list[BarceloHotel], end_date: date) -> list[PriceRow]:
    rows: list[PriceRow] = []
    for i, hotel in enumerate(hotels, 1):
        log.info("barcelo [%d/%d] %s", i, len(hotels), hotel.slug)
        try:
            rows.extend(scrape_barcelo_hotel(ctx, hotel, end_date))
        except Exception as exc:
            log.exception("barcelo %s crashed: %s", hotel.slug, exc)
    return rows
