from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta

from playwright.sync_api import BrowserContext  # kept for signature compatibility

from ..firecrawl_client import FirecrawlError, scrape_markdown
from ..models import PriceRow

log = logging.getLogger(__name__)

# The three "análises" the client asked for. Booking does not surface a
# teaser rate on the listing page without dates; longer stays (5+ nights)
# routinely return "no availability" for these luxury apartments, leaving
# the "normal" tier mostly null. (1, 2, 3) gives three distinct length-of-
# stay snapshots with the highest hit-rate — 3 nights is the "longer than
# a weekend, looks like a holiday" baseline that proxies for "normal" while
# still being short enough that Booking will quote it.
STAY_NIGHTS = (1, 2, 3)

# Booking shows a city-tax + VAT line that's NOT in the headline price; we
# leave price as-shown ("excludes city tax / VAT not shown" depending on
# stay), so client-side comparisons stay apples-to-apples with what a guest
# sees on screen.
BOOKING_BASE = "https://www.booking.com"
SCRAPE_THROTTLE_SECONDS = 0.2  # gentle pacing between Booking calls

# Headline-price patterns we accept, in priority order. They all match the
# room-card "total for N nights" cell rendered on the listing page.
HEADLINE_PATTERNS = [
    # "**€ 3,359 for 1 night**" — bold callout near the top of the listing
    re.compile(r"\*\*\s*€\s*([\d,.]+)\s*for\s+(\d+)\s+night", re.IGNORECASE),
    # "€ 3,359<br>1 night" or "€ 3,359 1 night" inside the room table
    re.compile(r"€\s*([\d,.]+)\s*(?:<br>|\s)\s*(\d+)\s+night", re.IGNORECASE),
    # "(€ 3,359)" total-for-stay reservation summary
    re.compile(r"\(\s*€\s*([\d,.]+)\s*\)\s*\|", re.IGNORECASE),
]


@dataclass(frozen=True)
class BookingListing:
    brand: str
    hotel_name: str
    hotel_id: str
    city: str
    slug: str

    @property
    def url(self) -> str:
        return f"{BOOKING_BASE}/hotel/pt/{self.slug}.en-gb.html"


LISTINGS: list[BookingListing] = [
    BookingListing(
        brand="Savoy Insular",
        hotel_name="Luxury in the City of Funchal - Savoy Insular V",
        hotel_id="savoy-insular-v",
        city="Funchal",
        slug="luxury-in-the-city-of-funchal-savoy-insular-v",
    ),
    BookingListing(
        brand="Savoy Monumentalis",
        hotel_name="Savoy Monumentalis VII Comfort Luxury",
        hotel_id="savoy-monumentalis-vii",
        city="Funchal",
        slug="savoy-monumentalis-vii-comfort-luxury",
    ),
]


def _parse_eur_amount(raw: str) -> float | None:
    raw = raw.strip()
    # Booking renders euros as "€ 3,256" (US thousand separator) or
    # "€ 3.256,50" (European). Disambiguate by the position of the last
    # separator: if that token has 1-2 digits, it's the decimal.
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        # Decide: 3,256 (thousands) vs 49,90 (decimal)
        tail = raw.rsplit(",", 1)[1]
        if len(tail) == 3:
            raw = raw.replace(",", "")
        else:
            raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _extract_headline_price(md: str, expected_nights: int) -> float | None:
    for pat in HEADLINE_PATTERNS[:2]:
        for m in pat.finditer(md):
            try:
                if int(m.group(2)) != expected_nights:
                    continue
            except (ValueError, IndexError):
                continue
            price = _parse_eur_amount(m.group(1))
            if price is not None:
                return price
    # Fallback: parenthesised total in summary table.
    m = HEADLINE_PATTERNS[2].search(md)
    if m:
        return _parse_eur_amount(m.group(1))
    return None


def _build_url(listing: BookingListing, checkin: date, nights: int) -> str:
    checkout = checkin + timedelta(days=nights)
    return (
        f"{listing.url}?checkin={checkin.isoformat()}&checkout={checkout.isoformat()}"
        f"&group_adults=2&no_rooms=1&selected_currency=EUR&lang=en-gb"
    )


def _scrape_one(
    listing: BookingListing, checkin: date, nights: int
) -> tuple[float | None, bool]:
    url = _build_url(listing, checkin, nights)
    try:
        md = scrape_markdown(
            url,
            actions=[
                {"type": "wait", "milliseconds": 4000},
                {"type": "scroll", "direction": "down", "amount": 1500},
                {"type": "wait", "milliseconds": 1500},
            ],
            wait_for_ms=4000,
            timeout_ms=60000,
        )
    except FirecrawlError as exc:
        log.warning("booking %s %s n=%d failed: %s", listing.hotel_id, checkin, nights, exc)
        return None, False
    price = _extract_headline_price(md, expected_nights=nights)
    if price is None:
        # No headline price found — most likely the date is sold out or the
        # minimum-stay constraint excludes this length. Distinguish "not
        # found" from "blocked": if markdown is suspiciously short, treat
        # as a render failure (False); otherwise as unavailable (True).
        looked_blocked = len(md) < 5000
        return None, not looked_blocked
    return price, True


def _weekly_anchors(today: date, end_date: date) -> list[date]:
    """Mondays from today through end_date — ~34 anchors over ~8 months.

    Booking is metered (~15 s per Firecrawl render), so daily granularity
    blows past the workflow's wall-clock budget; weekly Mondays give a
    consistent, repeatable cadence and ~204 calls per run instead of ~1500.
    """
    anchors: list[date] = []
    d = today
    # Snap forward to the next Monday (or stay on today if it's already Monday).
    if d.weekday() != 0:
        d += timedelta(days=(7 - d.weekday()) % 7)
    while d <= end_date:
        anchors.append(d)
        d += timedelta(days=7)
    return anchors


def _scrape_listing_stay(
    listing: BookingListing, today: date, end_date: date, nights: int
) -> list[PriceRow]:
    rows: list[PriceRow] = []
    consecutive_failures = 0
    for d in _weekly_anchors(today, end_date):
        # The latest possible check-in for an N-night stay ending in 2026 is
        # end_date - (N - 1). After that, the stay would spill into 2027.
        if d + timedelta(days=nights) > end_date + timedelta(days=1):
            continue
        price, captured = _scrape_one(listing, d, nights)
        if not captured:
            consecutive_failures += 1
            if consecutive_failures >= 5:
                log.error(
                    "booking %s n=%d: %d consecutive render failures, abandoning",
                    listing.hotel_id, nights, consecutive_failures,
                )
                break
        else:
            consecutive_failures = 0
        rows.append(
            PriceRow(
                brand=listing.brand,
                hotel_name=listing.hotel_name,
                hotel_id=listing.hotel_id,
                room_type="",
                room_id="",
                city=listing.city,
                date=d,
                price=price,
                currency="EUR",
                available=price is not None,
                stay_nights=nights,
                source_url=listing.url,
            )
        )
        time.sleep(SCRAPE_THROTTLE_SECONDS)
    priced = sum(1 for r in rows if r.price is not None)
    log.info(
        "booking %s n=%d -> %d rows (%d priced)",
        listing.hotel_id, nights, len(rows), priced,
    )
    return rows


def scrape_booking(_ctx: BrowserContext | None, end_date: date) -> list[PriceRow]:
    today = date.today()
    anchor_count = len(_weekly_anchors(today, end_date))
    log.info(
        "booking: %d listings × %d stay-lengths × %d weekly anchors = ~%d calls",
        len(LISTINGS), len(STAY_NIGHTS), anchor_count,
        len(LISTINGS) * len(STAY_NIGHTS) * anchor_count,
    )
    rows: list[PriceRow] = []
    for listing in LISTINGS:
        for nights in STAY_NIGHTS:
            rows.extend(_scrape_listing_stay(listing, today, end_date, nights))
    priced = sum(1 for r in rows if r.price is not None)
    log.info("booking: %d rows total (%d priced)", len(rows), priced)
    return rows
