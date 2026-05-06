from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta

from playwright.sync_api import BrowserContext, TimeoutError as PWTimeout

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

# The room-card headline "€ X for N nights" is the room+cleaning subtotal
# — what Booking shows in the room detail card. NOT what booking.com
# surfaces as "Today's price · Includes taxes and charges" in its main
# headline box, which is the number guests actually see and that the user
# wants to match. Booking's headline = base × nights × (1 + VAT) + cleaning
# + city_tax × adults × nights, where the four pieces are also rendered
# inside the room card markdown:
#   €1,647 per night   (base, pre-VAT)
#   €224.25 Cleaning fee per stay
#   €2 City tax per person per night, 4 % VAT
# We record the headline-equivalent total so the table matches booking.com
# row-for-row.
HEADLINE_RE = re.compile(
    r"€\s*([\d,.]+)\s*(?:for\s+)?(?:<br>|\s)+(\d+)\s+night",
    re.IGNORECASE,
)
PER_NIGHT_RE = re.compile(
    r"€\s*([\d,.]+)\s*(?:<br>|\s)+per\s+night",
    re.IGNORECASE,
)
CLEANING_RE = re.compile(
    r"€\s*([\d,.]+)\s+Cleaning\s+fee\s+per\s+stay",
    re.IGNORECASE,
)
CITY_TAX_RE = re.compile(
    r"€\s*([\d,.]+)\s+City\s+tax\s+per\s+person\s+per\s+night",
    re.IGNORECASE,
)
VAT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*VAT", re.IGNORECASE)
ADULTS = 2


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
    """Return Booking's "Today's price · Includes taxes and charges"
    equivalent for the requested stay length, picking the cheapest room
    on the page.

    Booking renders four pieces inside each room card. We combine them
    with the same formula booking.com uses for its headline box:

        total = base_per_night × nights × (1 + VAT)
              + cleaning_fee
              + city_tax × ADULTS × nights

    Verified against the live page on 2026-05-08 for Savoy Monumentalis VII
    (1 night, 2 adults):
        1647 × 1 × 1.04 + 224.25 + 2 × 2 × 1 = 1941.13 → €1,941 ✓
        which is exactly the "Today's price €1,941 Includes taxes and
        charges" the user screenshot showed.

    Falls back to the raw "€ X for N nights" headline if any of the
    components are missing — that yields the same number the room card
    shows (cleaning included, VAT and city tax excluded).
    """
    candidates: list[float] = []
    for h in HEADLINE_RE.finditer(md):
        try:
            if int(h.group(2)) != expected_nights:
                continue
        except (ValueError, IndexError):
            continue
        # Look at the ~600 char window around this headline for the
        # accompanying per-night, cleaning, city-tax, and VAT lines.
        window_start = max(0, h.start() - 400)
        window_end = min(len(md), h.end() + 400)
        window = md[window_start:window_end]
        per_night_m = PER_NIGHT_RE.search(window)
        cleaning_m = CLEANING_RE.search(window)
        vat_m = VAT_RE.search(window)
        city_m = CITY_TAX_RE.search(window)
        per_night = _parse_eur_amount(per_night_m.group(1)) if per_night_m else None
        cleaning = _parse_eur_amount(cleaning_m.group(1)) if cleaning_m else 0.0
        vat_pct = float(vat_m.group(1)) / 100.0 if vat_m else 0.0
        city_tax = _parse_eur_amount(city_m.group(1)) if city_m else 0.0
        if per_night is not None:
            total = (
                per_night * expected_nights * (1 + vat_pct)
                + (cleaning or 0.0)
                + (city_tax or 0.0) * ADULTS * expected_nights
            )
            candidates.append(round(total, 2))
            continue
        # Fallback: just the room-card headline value (cleaning included,
        # VAT/city-tax excluded). Better than dropping the row entirely.
        bare = _parse_eur_amount(h.group(1))
        if bare is not None:
            candidates.append(bare)
    if not candidates:
        return None
    return min(candidates)


def _build_url(listing: BookingListing, checkin: date, nights: int) -> str:
    checkout = checkin + timedelta(days=nights)
    return (
        f"{listing.url}?checkin={checkin.isoformat()}&checkout={checkout.isoformat()}"
        f"&group_adults=2&no_rooms=1&selected_currency=EUR&lang=en-gb"
    )


# Booking embeds the price card data as JSON inside the page. The keys we
# want surfaced from "b_legacy_data" / "b_raw_price" / "b_value":
#   b_raw_price       — Today's price total (€1941.13 for the user's example)
#   b_net_room_price  — base × nights, pre-VAT, pre-cleaning
B_RAW_PRICE_RE = re.compile(r'"b_raw_price"\s*:\s*([\d.]+)')


def _extract_today_price_from_html(html: str) -> float | None:
    """Pick the lowest `b_raw_price` across all room-rate JSON blobs.

    Each available room emits its own b_raw_price; cheapest matches what
    Booking calls "Today's price · Includes taxes and charges" in its
    headline box, which is the value the client wants on the dashboard.
    """
    candidates: list[float] = []
    for m in B_RAW_PRICE_RE.finditer(html):
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        if v > 0:
            candidates.append(v)
    if not candidates:
        return None
    return round(min(candidates), 2)


def _scrape_via_playwright(
    page, listing: BookingListing, checkin: date, nights: int
) -> tuple[float | None, bool]:
    """Direct Playwright scrape — bypasses Firecrawl entirely.

    Booking renders a JSON blob with the exact "Today's price" total
    (b_raw_price field) in the page HTML once the room-availability
    section has hydrated. We just have to wait for it and pluck the
    minimum.
    """
    url = _build_url(listing, checkin, nights)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except PWTimeout:
        return None, False
    # Wait for the room-card section to appear (it carries the price JSON).
    try:
        page.wait_for_selector("#hp_availability_style_changes", timeout=20000)
    except PWTimeout:
        # Page loaded but availability never rendered → genuinely no
        # availability for this date / stay-length combo.
        html = page.content()
        return None, "Access Denied" not in html and "captcha" not in html.lower()
    # Settle async hydration of the price JSON.
    page.wait_for_timeout(2000)
    page.evaluate("window.scrollTo(0, 1500)")
    page.wait_for_timeout(2000)
    html = page.content()
    if "Access Denied" in html or "Are you a robot" in html:
        return None, False
    price = _extract_today_price_from_html(html)
    return price, price is not None or len(html) > 500_000


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


def scrape_booking(ctx: BrowserContext | None, end_date: date) -> list[PriceRow]:
    today = date.today()
    plan = _build_url_plan(today, end_date)
    log.info(
        "booking: %d (listing, date, nights) entries via Playwright direct",
        len(plan),
    )

    rows: list[PriceRow] = []
    consecutive_failures = 0

    if ctx is None:
        log.error("booking: no playwright context, cannot scrape")
        return rows

    page = ctx.new_page()
    try:
        for idx, (listing, d, n) in enumerate(plan, 1):
            try:
                price, captured = _scrape_via_playwright(page, listing, d, n)
            except Exception as exc:
                log.warning("booking %s %s n=%d crash: %s", listing.hotel_id, d, n, exc)
                price, captured = None, False

            if not captured:
                consecutive_failures += 1
                if consecutive_failures >= 8:
                    log.error(
                        "booking: %d consecutive blocked/failed pages — abandoning remaining %d",
                        consecutive_failures, len(plan) - idx,
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
                    stay_nights=n,
                    source_url=listing.url,
                )
            )
            if idx % 25 == 0:
                priced_so_far = sum(1 for r in rows if r.price is not None)
                log.info("booking: %d/%d done (%d priced so far)", idx, len(plan), priced_so_far)
    finally:
        page.close()

    by_stay: dict[int, tuple[int, int]] = {}
    for r in rows:
        n = r.stay_nights or 0
        rows_n, priced_n = by_stay.get(n, (0, 0))
        by_stay[n] = (rows_n + 1, priced_n + (1 if r.price is not None else 0))
    for n in sorted(by_stay):
        rn, pn = by_stay[n]
        log.info("booking: stay=%dn -> %d rows (%d priced)", n, rn, pn)
    log.info(
        "booking: %d rows total (%d priced)",
        len(rows), sum(1 for r in rows if r.price is not None),
    )
    return rows
