from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import requests
from playwright.sync_api import BrowserContext  # kept for signature compatibility
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .models import PriceRow

log = logging.getLogger(__name__)

HOTEL_ID = "100380501"
HOTEL_NAME = "Three House Hotel"
CITY = "Funchal"
BRAND = "Threehouse"
SOURCE_URL = "https://www.threehouse.com/"

# Mirai public endpoints — discovered by intercepting the widget's network
# calls on www.threehouse.com. No auth needed, used by the official calendar.
PRICE_INDEX_URL = "https://index-price.mirai.com/{hotel_id}/{mmYYYY}.json"  # hotel aggregate per month
ROOM_INDEX_URL = "https://index-room.mirai.com/{hotel_id}/{room_id}.json"  # per-room, full year, one shot

# Empirical tax handling, cross-checked against the Mirai calendar + the hotel's
# own rate detail popup:
#   - index-price.mirai.com (hotel aggregate) returns the calendar value, which
#     is the cheapest room's base price × 1.04 — i.e. already "Inclui impostos"
#     (Madeira hotel IVA = 4 %).
#   - index-room.mirai.com (per room) returns the base price WITHOUT IVA, so
#     we multiply by 1.04 here to keep every row in the sheet in the same
#     "Inclui impostos" format.
#   - Funchal's taxa municipal de dormida (2 €/adult/night) is not in either
#     endpoint; we expose it as a derived display in the UI, not in `price`.
MADEIRA_HOTEL_IVA = 0.04

REQUEST_TIMEOUT = 15


@dataclass(frozen=True)
class Room:
    room_id: str
    room_type: str
    slug: str

    @property
    def url(self) -> str:
        return f"https://www.threehouse.com/estadia/{self.slug}/"


# Verified from /estadia/ URLs on www.threehouse.com.
ROOMS: list[Room] = [
    Room("85060", "Panorama Studio", "studio-85060"),
    Room("85064", "Two-Bedroom Superior Apartment", "apartamento-t2-superior-85064"),
    Room("85063", "Two-Bedroom Apartment", "apartamento-t2-85063"),
    Room("85062", "One-Bedroom Superior Apartment", "apartamento-t1-superior-85062"),
    Room("85061", "One-Bedroom Apartment", "apartamento-t1-85061"),
]

AGGREGATE_ROOM_LABEL = "All rooms (lowest)"


class MiraiError(RuntimeError):
    pass


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1.5, min=1, max=8),
    retry=retry_if_exception_type(MiraiError),
)
def _get_json(url: str) -> dict[str, Any]:
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise MiraiError(f"network: {exc}") from exc
    if r.status_code == 404:
        return {}
    if not r.ok:
        raise MiraiError(f"status {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except ValueError as exc:
        raise MiraiError(f"non-JSON: {exc}") from exc


def _month_iter(start: date, end: date):
    cur = date(start.year, start.month, 1)
    while cur <= end:
        yield cur.year, cur.month
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)


def _parse_mirai_date(s: str) -> date | None:
    # Mirai returns "DD/MM/YYYY".
    try:
        d, m, y = s.split("/")
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def fetch_aggregate_prices(hotel_id: str, start: date, end: date) -> dict[date, float]:
    out: dict[date, float] = {}
    for y, m in _month_iter(start, end):
        url = PRICE_INDEX_URL.format(hotel_id=hotel_id, mmYYYY=f"{m:02d}{y}")
        try:
            data = _get_json(url)
        except MiraiError as exc:
            log.warning("threehouse: aggregate %04d-%02d failed: %s", y, m, exc)
            continue
        prices = data.get("prices") or {}
        for s, price in prices.items():
            d = _parse_mirai_date(s)
            if d and start <= d <= end and isinstance(price, (int, float)):
                out[d] = float(price)
    return out


def fetch_room_prices(hotel_id: str, room_id: str, start: date, end: date) -> dict[date, float]:
    url = ROOM_INDEX_URL.format(hotel_id=hotel_id, room_id=room_id)
    try:
        data = _get_json(url)
    except MiraiError as exc:
        log.warning("threehouse: room %s failed: %s", room_id, exc)
        return {}
    dates = data.get("dates") or {}
    out: dict[date, float] = {}
    for s, price in dates.items():
        d = _parse_mirai_date(s)
        if d and start <= d <= end and isinstance(price, (int, float)):
            # Normalise to "Inclui impostos" so rows compare apples-to-apples
            # with the aggregate and with what the on-site calendar displays.
            out[d] = round(float(price) * (1 + MADEIRA_HOTEL_IVA), 2)
    return out


def _emit_row(
    room_type: str,
    room_id: str,
    source_url: str,
    d: date,
    price: float | None,
) -> PriceRow:
    return PriceRow(
        brand=BRAND,
        hotel_name=HOTEL_NAME,
        hotel_id=HOTEL_ID,
        room_type=room_type,
        room_id=room_id,
        city=CITY,
        date=d,
        price=price,
        currency="EUR",
        available=price is not None,
        source_url=source_url,
    )


def scrape_threehouse(_ctx: BrowserContext | None, end_date: date) -> list[PriceRow]:
    today = date.today()

    log.info(
        "threehouse: fetching aggregate (%d months) + %d rooms via Mirai index APIs",
        (end_date.year - today.year) * 12 + end_date.month - today.month + 1,
        len(ROOMS),
    )

    aggregate = fetch_aggregate_prices(HOTEL_ID, today, end_date)
    log.info("threehouse: aggregate -> %d priced days", len(aggregate))

    per_room: dict[str, dict[date, float]] = {}
    for room in ROOMS:
        prices = fetch_room_prices(HOTEL_ID, room.room_id, today, end_date)
        per_room[room.room_id] = prices
        log.info(
            "threehouse: room %s (%s) -> %d priced days",
            room.room_type, room.room_id, len(prices),
        )

    rows: list[PriceRow] = []

    # Aggregate rows (one per day today..end_date).
    d = today
    while d <= end_date:
        rows.append(
            _emit_row(AGGREGATE_ROOM_LABEL, "", SOURCE_URL, d, aggregate.get(d)),
        )
        d += timedelta(days=1)

    # Per-room rows.
    for room in ROOMS:
        prices = per_room.get(room.room_id, {})
        d = today
        while d <= end_date:
            rows.append(
                _emit_row(room.room_type, room.room_id, room.url, d, prices.get(d)),
            )
            d += timedelta(days=1)

    with_price = sum(1 for r in rows if r.price is not None)
    log.info("threehouse: %d rows (%d with price)", len(rows), with_price)
    return rows
