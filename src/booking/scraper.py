from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta

from playwright.sync_api import BrowserContext  # kept for signature compatibility

from ..firecrawl_client import FirecrawlError, scrape_batch_markdown, scrape_markdown
from ..models import PriceRow

log = logging.getLogger(__name__)

# Stay lengths Luis Calado asked us to track. Per-night rate varies
# dramatically with length (Booking's "single-night premium" rules):
# Savoy Monumentalis on 2026-09-01 quotes 3,737 €/night for 1 night,
# 1,868 €/night for 2 nights, and 534 €/night for 7 nights — same
# total stay price, very different per-night signal for the client.
STAY_NIGHTS = (1, 2, 3, 7)

# Booking shows a city-tax + VAT line that's NOT in the headline price; we
# leave price as-shown ("excludes city tax / VAT not shown" depending on
# stay), so client-side comparisons stay apples-to-apples with what a guest
# sees on screen.
BOOKING_BASE = "https://www.booking.com"
SCRAPE_THROTTLE_SECONDS = 0.2  # gentle pacing between Booking calls

# Total-stay headline ("€ X for N night(s)" or "€ X<br>N nights" inside a
# room card). This is the number Booking shows in its own calendar
# overview, including cleaning fee — the "from €X" the user sees when
# scrolling through May/June. We record it as `price` so the table can be
# compared 1-to-1 against booking.com without subtracting fees.
HEADLINE_RE = re.compile(
    r"€\s*([\d,.]+)\s*(?:for\s+)?(?:<br>|\s)+(\d+)\s+night",
    re.IGNORECASE,
)

# Kept for diagnostics / future per-night display, but not used as the
# primary `price` value any more.
PER_NIGHT_RE = re.compile(
    r"€\s*([\d,.]+)\s*(?:<br>|\s)+per\s+night",
    re.IGNORECASE,
)


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


def _extract_total_stay_price(md: str, expected_nights: int) -> float | None:
    """Return the lowest "€ X for N night(s)" total across all rooms on the
    page, but only after confirming the page's headline reports the same
    stay length we requested — matches Booking's calendar "from €X"
    semantic (cheapest room, requested stay length, total stay including
    cleaning fee).

    Without the headline guard, Booking's minimum-stay enforcement leaks:
    a request for 1 night may render a 2-night card, and we'd silently
    record the longer-stay total against the 1-night row.
    Without the MIN aggregation, we'd record whichever total Firecrawl
    happened to render first instead of the cheapest available — diverging
    from what Booking displays in its own calendar overview.
    """
    candidates: list[float] = []
    for h in HEADLINE_RE.finditer(md):
        try:
            if int(h.group(2)) != expected_nights:
                continue
        except (ValueError, IndexError):
            continue
        total = _parse_eur_amount(h.group(1))
        if total is not None:
            candidates.append(total)
    if not candidates:
        return None
    return min(candidates)


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
    price = _extract_total_stay_price(md, expected_nights=nights)
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


DAILY_HORIZON_DAYS = 28  # how far out we keep daily 1n granularity


def _build_url_plan(today: date, end_date: date) -> list[tuple[BookingListing, date, int]]:
    """Build the full set of (listing, date, nights) we want to fetch.

    Density was tuned down on 2026-05-06 after a daily-everywhere plan
    (~734 URLs) blew the Firecrawl credit budget mid-batch (402). Current
    shape is the cheapest version that still satisfies "calendar shows
    real per-day prices for the near-term window the client cares about":

    - Daily 1-night for the next DAILY_HORIZON_DAYS (≈28 days × 2 listings
      = 56 URLs). That's the part of the calendar guests actually book
      against.
    - Weekly Mondays for 1-night for the rest of the year so the heatmap
      isn't blank past the horizon (~33 × 2 = 66 URLs).
    - Weekly Mondays for 2/3/7-night so the per-night ratio analysis
      still has data (~35 × 3 × 2 = 210 URLs).
    Total per run ≈ 332 URLs, well within the free Firecrawl tier.
    """
    plan: list[tuple[BookingListing, date, int]] = []
    horizon = today + timedelta(days=DAILY_HORIZON_DAYS)
    weekly_set = set(_weekly_anchors(today, end_date))
    d = today
    while d <= end_date:
        is_weekly = d in weekly_set
        within_horizon = d <= horizon
        for listing in LISTINGS:
            if (within_horizon or is_weekly) and (d + timedelta(days=1) <= end_date + timedelta(days=1)):
                plan.append((listing, d, 1))
            if is_weekly:
                for n in (2, 3, 7):
                    if d + timedelta(days=n) <= end_date + timedelta(days=1):
                        plan.append((listing, d, n))
        d += timedelta(days=1)
    return plan


def scrape_booking(_ctx: BrowserContext | None, end_date: date) -> list[PriceRow]:
    today = date.today()
    plan = _build_url_plan(today, end_date)
    url_to_meta: dict[str, tuple[BookingListing, date, int]] = {}
    for listing, d, n in plan:
        url_to_meta[_build_url(listing, d, n)] = (listing, d, n)

    log.info(
        "booking: %d urls (daily 1n + weekly 2/3/7n) via Firecrawl batch",
        len(url_to_meta),
    )

    actions = [
        {"type": "wait", "milliseconds": 4000},
        {"type": "scroll", "direction": "down", "amount": 1500},
        {"type": "wait", "milliseconds": 1500},
    ]

    try:
        results = scrape_batch_markdown(
            list(url_to_meta.keys()),
            actions=actions,
            wait_for_ms=4000,
            timeout_ms=60000,
            poll_interval_s=10.0,
            max_wait_s=3000,  # 50 min cap; workflow timeout is 90 min
        )
    except FirecrawlError as exc:
        log.error("booking: batch failed (%s) — falling back to serial", exc)
        results = {}

    rows: list[PriceRow] = []
    for url, (listing, d, n) in url_to_meta.items():
        md = results.get(url)
        if md is None:
            # Batch missed this URL (or batch failed entirely). Try a single
            # serial scrape as a per-row fallback so we don't drop the row.
            try:
                md = scrape_markdown(url, actions=actions, wait_for_ms=4000, timeout_ms=60000)
            except FirecrawlError:
                md = None
        price = _extract_total_stay_price(md, expected_nights=n) if md else None
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
                stay_nights=n,
                source_url=listing.url,
            )
        )

    by_stay: dict[int, tuple[int, int]] = {}  # nights -> (rows, priced)
    for r in rows:
        n = r.stay_nights or 0
        rows_n, priced_n = by_stay.get(n, (0, 0))
        by_stay[n] = (rows_n + 1, priced_n + (1 if r.price is not None else 0))
    for n in sorted(by_stay):
        rn, pn = by_stay[n]
        log.info("booking: stay=%dn -> %d rows (%d priced)", n, rn, pn)
    log.info("booking: %d rows total (%d priced)", len(rows), sum(1 for r in rows if r.price is not None))
    return rows
