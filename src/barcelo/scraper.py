from __future__ import annotations

import json
import logging
import re
from calendar import monthrange
from datetime import date, timedelta
from typing import Any, Iterable

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


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1.5, min=2, max=15),
    retry=retry_if_exception_type(BarceloFetchError),
)
def _fetch_window_playwright(
    page, hotel: BarceloHotel, check_in: date, check_out: date
) -> list[tuple[date, float | None, bool]]:
    """Use Playwright's request context (carries _abck cookie from page navigation)."""
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
    }
    url = AVAILABILITY_URL.format(id=hotel.hotel_id)
    try:
        resp = page.request.post(url, data=json.dumps(body), headers=headers, timeout=30000)
    except Exception as exc:
        raise BarceloFetchError(f"network: {exc}") from exc

    if resp.status >= 500 or resp.status == 403:
        raise BarceloFetchError(f"status {resp.status}")
    if not resp.ok:
        log.debug("barcelo %s %s..%s -> %s", hotel.slug, check_in, check_out, resp.status)
        return []
    try:
        data = resp.json()
    except Exception:
        return []
    return list(_iter_daily_prices(data))


def scrape_barcelo_hotel(ctx: BrowserContext, hotel: BarceloHotel, end_date: date) -> list[PriceRow]:
    today = date.today()
    captured: dict[date, tuple[float | None, bool]] = {}

    # Open the hotel page in a real browser so Akamai's JS challenge sets the _abck cookie.
    page = ctx.new_page()
    log.info("barcelo: warming Akamai session via %s", hotel.page_url)
    try:
        page.goto(hotel.page_url, wait_until="domcontentloaded", timeout=60000)
        # Simulate human interaction so Akamai's sensor_data fires.
        for y in (200, 600, 1200, 800, 400):
            page.mouse.move(500 + y // 3, 300 + y // 5)
            page.evaluate(f"window.scrollTo(0, {y})")
            page.wait_for_timeout(800)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        # Wait for _abck cookie up to 25s.
        for _ in range(25):
            cookies = ctx.cookies()
            if any(c["name"].startswith("_abck") for c in cookies):
                break
            page.wait_for_timeout(1000)
        cookies = ctx.cookies()
        abck = next((c for c in cookies if c["name"].startswith("_abck")), None)
        log.info(
            "barcelo: cookies=%d _abck=%s (len=%s)",
            len(cookies), bool(abck), len(abck["value"]) if abck else 0,
        )
    except Exception as exc:
        log.warning("barcelo: warmup nav failed (%s)", exc)

    for win_start, win_end in _month_windows(today, end_date):
        check_out = win_end + timedelta(days=1)
        try:
            rows = _fetch_window_playwright(page, hotel, win_start, check_out)
        except BarceloFetchError as exc:
            log.warning("barcelo %s %s..%s failed: %s", hotel.slug, win_start, win_end, exc)
            continue
        for d, price, avail in rows:
            if win_start <= d <= win_end:
                captured.setdefault(d, (price, avail))

    page.close()

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
