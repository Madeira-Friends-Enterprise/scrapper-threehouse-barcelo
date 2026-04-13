from __future__ import annotations

import json
import logging
import re
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

from playwright.sync_api import BrowserContext
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..models import PriceRow
from .discover import BarceloHotel

log = logging.getLogger(__name__)

BRAND = "Barceló"
AVAILABILITY_URL = (
    "https://reservation-api.barcelo.com/hotel-availability-adapter/v1/hotels/{id}/availability"
)

DATE_KEYS = (
    "date", "day", "checkIn", "stayDate", "stay_date",
    "arrivalDate", "night", "nightDate",
)
PRICE_KEYS = (
    "totalAmount", "amount", "price", "minPrice", "rate",
    "nightlyRate", "bestPrice", "finalPrice", "grossPrice", "netPrice",
)
PRICE_SUBKEYS = ("amount", "value", "gross", "total", "min", "final")

_SCHEMA_LOGGED = False


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


def _coerce_price(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        raw = re.sub(r"[^\d.,-]", "", value).strip()
        if not raw:
            return None
        if "," in raw and "." in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif "," in raw:
            raw = raw.replace(",", ".")
        try:
            return float(raw)
        except ValueError:
            return None
    if isinstance(value, dict):
        for k in PRICE_SUBKEYS:
            if k in value and value[k] is not None:
                p = _coerce_price(value[k])
                if p is not None:
                    return p
    return None


def _iter_daily_prices(payload: Any) -> Iterable[tuple[date, float | None, bool]]:
    stack: list[Any] = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            d_raw: Any = None
            for k in DATE_KEYS:
                if k in node and node[k]:
                    d_raw = node[k]
                    break
            price_candidate: Any = None
            for k in PRICE_KEYS:
                if k in node and node[k] is not None:
                    price_candidate = node[k]
                    break
            if isinstance(d_raw, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", d_raw):
                try:
                    dd = date.fromisoformat(d_raw[:10])
                    price = _coerce_price(price_candidate)
                    avail = node.get("available")
                    if avail is None:
                        avail = node.get("isAvailable", price is not None)
                    yield dd, price, bool(avail)
                    continue
                except (TypeError, ValueError):
                    pass
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def _log_schema_sample(data: Any) -> None:
    try:
        top_keys = list(data.keys()) if isinstance(data, dict) else f"<{type(data).__name__}>"
        log.info("barcelo: schema top-level keys: %s", top_keys)
        sample = json.dumps(data, ensure_ascii=False, indent=2, default=str)[:1500]
        log.info("barcelo: schema sample (1500 chars):\n%s", sample)
        Path("barcelo_schema_dump.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        log.info("barcelo: schema dumped to barcelo_schema_dump.json")
    except Exception as exc:
        log.warning("barcelo: schema log failed: %s", exc)


@retry(
    reraise=True,
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1.5, min=1, max=5),
    retry=retry_if_exception_type(BarceloFetchError),
)
def _fetch_window_playwright(
    page, hotel: BarceloHotel, check_in: date, check_out: date
) -> list[tuple[date, float | None, bool]]:
    global _SCHEMA_LOGGED
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

    status = resp.status
    try:
        body_text = resp.text()
    except Exception:
        body_text = ""
    preview = body_text[:180].replace("\n", " ")
    log.info(
        "barcelo %s %s..%s -> status=%d len=%d preview=%r",
        hotel.slug, check_in, check_out, status, len(body_text), preview,
    )

    if status >= 500 or status in (401, 403, 429):
        raise BarceloFetchError(f"status {status}")
    if status != 200:
        return []

    try:
        data = resp.json()
    except Exception as exc:
        log.warning("barcelo: non-JSON response %s..%s: %s", check_in, check_out, exc)
        return []

    if not _SCHEMA_LOGGED:
        _log_schema_sample(data)
        _SCHEMA_LOGGED = True

    rows = list(_iter_daily_prices(data))
    priced = sum(1 for _, p, _ in rows if p is not None)
    log.info(
        "barcelo %s..%s -> %d day rows (%d priced)",
        check_in, check_out, len(rows), priced,
    )
    return rows


def scrape_barcelo_hotel(ctx: BrowserContext, hotel: BarceloHotel, end_date: date) -> list[PriceRow]:
    today = date.today()
    captured: dict[date, tuple[float | None, bool]] = {}

    page = ctx.new_page()
    log.info("barcelo: warming Akamai session via %s", hotel.page_url)
    try:
        page.goto(hotel.page_url, wait_until="domcontentloaded", timeout=60000)
        for y in (200, 600, 1200, 800, 400):
            page.mouse.move(500 + y // 3, 300 + y // 5)
            page.evaluate(f"window.scrollTo(0, {y})")
            page.wait_for_timeout(800)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
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

    consecutive_failures = 0
    for win_start, win_end in _month_windows(today, end_date):
        check_out = win_end + timedelta(days=1)
        try:
            rows = _fetch_window_playwright(page, hotel, win_start, check_out)
            consecutive_failures = 0
        except BarceloFetchError as exc:
            consecutive_failures += 1
            log.warning(
                "barcelo %s %s..%s failed (%d consecutive): %s",
                hotel.slug, win_start, win_end, consecutive_failures, exc,
            )
            if consecutive_failures >= 2:
                log.error(
                    "barcelo: circuit-breaker open after %d consecutive failures, "
                    "abandoning remaining windows",
                    consecutive_failures,
                )
                break
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
