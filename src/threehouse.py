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

NEXT_MONTH_SELECTOR = (
    "[data-twin='rates'] button[aria-label*='seguinte' i], "
    "[data-twin='rates'] button[aria-label*='next' i], "
    "[data-twin='rates'] button[aria-label*='pr\u00f3ximo' i], "
    "[data-twin='rates'] [class*='next-month'], "
    "[data-twin='rates'] .calendar-next, "
    "[data-twin='rates'] button:has-text('\u203a'), "
    "button[aria-label*='seguinte' i], "
    "button[aria-label*='next' i]"
)


def _parse_price(raw: str) -> float | None:
    raw = raw.strip()
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_month_block(block: str, year: int, month: int) -> list[tuple[date, float | None]]:
    last_day = monthrange(year, month)[1]
    out: list[tuple[date, float | None]] = []
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
            out.append((date(year, month, d), None))
            d += 1
            i = j + 1
            continue
        m = re.match(r"(\d{1,4}(?:[.,]\d{1,2})?)\s*€", block[j:])
        if m:
            price = _parse_price(m.group(1))
            out.append((date(year, month, d), price))
            d += 1
            i = j + m.end()
            continue
        i += 1
    return out


def parse_calendar_markdown(md: str) -> list[tuple[date, float | None]]:
    matches = list(MONTH_HEADER_RE.finditer(md))
    if not matches:
        return []
    out: list[tuple[date, float | None]] = []
    for idx, m in enumerate(matches):
        name = m.group(1).lower().replace("ç", "c")
        # Normalise "março" variants
        month_num = MONTHS_PT.get(name) or MONTHS_PT.get(m.group(1).lower())
        if not month_num:
            continue
        year = int(m.group(2))
        block_start = m.end()
        block_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(md)
        block = md[block_start:block_end]
        # Cut the block at the first non-calendar marker (explanatory text).
        cutoff = re.search(r"Pre[çc]os aproximados|Quem\s*\d|Promo[çc][ãa]o|Pesquisar", block)
        if cutoff:
            block = block[: cutoff.start()]
        out.extend(_parse_month_block(block, year, month_num))
    return out


def _build_actions(click_count: int) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = [
        {"type": "wait", "milliseconds": 3000},
        {"type": "scroll", "direction": "down", "amount": 600},
        {"type": "wait", "milliseconds": 1500},
    ]
    for _ in range(click_count):
        actions.append({"type": "click", "selector": NEXT_MONTH_SELECTOR})
        actions.append({"type": "wait", "milliseconds": 1200})
    return actions


def scrape_threehouse(_ctx: BrowserContext | None, end_date: date) -> list[PriceRow]:
    today = date.today()
    months_needed = (end_date.year - today.year) * 12 + (end_date.month - today.month) + 1

    captured: dict[date, float | None] = {}

    # Each Firecrawl call renders ~2 months. Advance by 2 months per call.
    call_count = max(1, (months_needed + 1) // 2 + 1)
    for call_idx in range(call_count):
        actions = _build_actions(click_count=call_idx * 2)
        try:
            md = scrape_markdown(
                SOURCE_URL,
                actions=actions,
                wait_for_ms=4000,
                timeout_ms=60000,
            )
        except FirecrawlError as exc:
            log.warning("threehouse: firecrawl call %d failed: %s", call_idx, exc)
            continue

        entries = parse_calendar_markdown(md)
        new_count = 0
        for d, price in entries:
            if d in captured:
                continue
            if today <= d <= end_date:
                captured[d] = price
                new_count += 1
        log.info(
            "threehouse: call %d advanced=%d months, parsed=%d entries, new=%d",
            call_idx, call_idx * 2, len(entries), new_count,
        )

        max_captured = max(captured.keys(), default=today)
        if max_captured >= end_date:
            break

    rows: list[PriceRow] = []
    d = today
    while d <= end_date:
        price = captured.get(d)
        rows.append(
            PriceRow(
                brand=BRAND,
                hotel_name=HOTEL_NAME,
                hotel_id=HOTEL_ID,
                city=CITY,
                date=d,
                price=price,
                available=price is not None,
                source_url=SOURCE_URL,
            )
        )
        d += timedelta(days=1)

    with_price = sum(1 for r in rows if r.price is not None)
    log.info("threehouse: %d rows (%d with price)", len(rows), with_price)
    return rows
