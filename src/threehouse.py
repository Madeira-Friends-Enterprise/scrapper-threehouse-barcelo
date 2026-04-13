from __future__ import annotations

import logging
import re
from calendar import monthrange
from datetime import date, timedelta
from typing import Any

from playwright.sync_api import BrowserContext  # kept for signature compatibility

from .firecrawl_client import FirecrawlError, scrape_markdown
from .models import PriceRow

log = logging.getLogger(__name__)

HOTEL_ID = "100380501"
HOTEL_NAME = "Three House Hotel"
CITY = "Funchal"
BRAND = "Threehouse"
SOURCE_URL = "https://www.threehouse.com/"

MONTHS_PT: dict[str, int] = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}

MONTH_HEADER_RE = re.compile(
    r"(janeiro|fevereiro|mar[çc]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)"
    r"\s+(\d{4})\s*segterquaquisex\w*bdom",
    re.IGNORECASE,
)

# Price token: digits (with optional . or , as thousand/decimal separators) followed by a currency marker.
# Accept €, $, USD, EUR. Lowercase-insensitive.
PRICE_TOKEN_RE = re.compile(
    r"(\d{1,4}(?:[.,]\d{1,3})?)\s*(€|\$|EUR|USD)",
    re.IGNORECASE,
)


def _parse_price(raw: str) -> float | None:
    raw = raw.strip()
    if "," in raw and "." in raw:
        # European thousand format "1.234,56" → 1234.56
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_month_block(block: str, year: int, month: int) -> list[tuple[date, float | None, str]]:
    """Return list of (date, price-or-None, currency-or-empty)."""
    last_day = monthrange(year, month)[1]
    out: list[tuple[date, float | None, str]] = []
    d = 1
    i = 0
    n = len(block)
    while d <= last_day and i < n:
        ds = str(d)
        if not block.startswith(ds, i):
            i += 1
            continue
        j = i + len(ds)
        if j < n and block[j] == "-":
            out.append((date(year, month, d), None, ""))
            d += 1
            i = j + 1
            continue
        m = PRICE_TOKEN_RE.match(block[j:])
        if m:
            price = _parse_price(m.group(1))
            sym = m.group(2).upper()
            curr = "EUR" if sym in ("€", "EUR") else ("USD" if sym in ("$", "USD") else "")
            out.append((date(year, month, d), price, curr))
            d += 1
            i = j + m.end()
            continue
        i += 1
    return out


def parse_calendar_markdown(md: str) -> list[tuple[date, float | None, str]]:
    """Parse all month blocks found in markdown, dedupe by date keeping the first priced hit."""
    matches = list(MONTH_HEADER_RE.finditer(md))
    if not matches:
        return []
    by_date: dict[date, tuple[float | None, str]] = {}
    for idx, m in enumerate(matches):
        name = m.group(1).lower().replace("ç", "c")
        month_num = MONTHS_PT.get(name) or MONTHS_PT.get(m.group(1).lower())
        if not month_num:
            continue
        year = int(m.group(2))
        block_start = m.end()
        block_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(md)
        block = md[block_start:block_end]
        cutoff = re.search(r"Pre[çc]os aproximados|Quem\s*\d|Promo[çc][ãa]o|Pesquisar", block)
        if cutoff:
            block = block[: cutoff.start()]
        for d, price, curr in _parse_month_block(block, year, month_num):
            prev = by_date.get(d)
            # Prefer priced entry over None-entry so later widgets don't overwrite a price with None.
            if prev is None or (prev[0] is None and price is not None):
                by_date[d] = (price, curr)
    return [(d, p, c) for d, (p, c) in sorted(by_date.items())]


def _checkin_url(d: date) -> str:
    """The Mirai widget on www.threehouse.com navigates when given ?checkin=DD/MM/YYYY."""
    return f"{SOURCE_URL}?checkin={d.day:02d}/{d.month:02d}/{d.year}"


def _month_anchors(today: date, end_date: date) -> list[date]:
    """One anchor per 2-month bucket. Each Firecrawl call renders anchor's month + next month."""
    anchors: list[date] = [today]
    cur = date(today.year, today.month, 1)
    # Advance by 2 months at a time from the START of the next uncovered bucket.
    while True:
        # Jump 2 months ahead.
        m = cur.month + 2
        y = cur.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        cur = date(y, m, 1)
        if cur > end_date:
            break
        anchors.append(cur)
    return anchors


def scrape_threehouse(_ctx: BrowserContext | None, end_date: date) -> list[PriceRow]:
    today = date.today()
    anchors = _month_anchors(today, end_date)
    log.info("threehouse: %d firecrawl anchors across %s..%s", len(anchors), today, end_date)

    captured: dict[date, tuple[float | None, str]] = {}

    for idx, anchor in enumerate(anchors):
        url = _checkin_url(anchor)
        try:
            md = scrape_markdown(
                url,
                actions=[{"type": "wait", "milliseconds": 4000}],
                wait_for_ms=4000,
                timeout_ms=60000,
            )
        except FirecrawlError as exc:
            log.warning("threehouse: firecrawl anchor %d (%s) failed: %s", idx, anchor, exc)
            continue

        entries = parse_calendar_markdown(md)
        new_count = 0
        for d, price, curr in entries:
            if not (today <= d <= end_date):
                continue
            prev = captured.get(d)
            if prev is None:
                captured[d] = (price, curr)
                new_count += 1
            elif prev[0] is None and price is not None:
                captured[d] = (price, curr)
        log.info(
            "threehouse: anchor %d (%s) parsed=%d new=%d total=%d",
            idx, anchor, len(entries), new_count, len(captured),
        )

    rows: list[PriceRow] = []
    d = today
    while d <= end_date:
        price, curr = captured.get(d, (None, ""))
        rows.append(
            PriceRow(
                brand=BRAND,
                hotel_name=HOTEL_NAME,
                hotel_id=HOTEL_ID,
                city=CITY,
                date=d,
                price=price,
                currency=curr or "EUR",
                available=price is not None,
                source_url=SOURCE_URL,
            )
        )
        d += timedelta(days=1)

    with_price = sum(1 for r in rows if r.price is not None)
    log.info("threehouse: %d rows (%d with price)", len(rows), with_price)
    return rows
