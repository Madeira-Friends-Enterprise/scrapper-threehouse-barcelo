from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import Any, Iterable

from playwright.sync_api import BrowserContext, Page, TimeoutError as PWTimeout

from .models import PriceRow

log = logging.getLogger(__name__)

HOTEL_ID = "100380501"
HOTEL_NAME = "Three House Hotel"
CITY = "Funchal"
BRAND = "Threehouse"
SOURCE_URL = "https://www.threehouse.com/"

RATES_URL = (
    "https://twin.mirai.com/rates/index.html"
    f"?id={HOTEL_ID}&lang=pt-PT&origin=https://www.threehouse.com"
)


def _months_between(start: date, end: date) -> list[tuple[int, int]]:
    months: list[tuple[int, int]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def _iter_prices_from_json(payload: Any) -> Iterable[tuple[date, float | None, bool]]:
    """Best-effort walker: Mirai payloads vary, so we scan recursively."""
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            d = node.get("date") or node.get("day") or node.get("checkin")
            p = (
                node.get("price")
                or node.get("rate")
                or node.get("minPrice")
                or node.get("amount")
            )
            if isinstance(d, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
                try:
                    dd = date.fromisoformat(d)
                    price = float(p) if p is not None else None
                    avail = bool(node.get("available", price is not None))
                    yield dd, price, avail
                    continue
                except (TypeError, ValueError):
                    pass
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def _collect_dom_prices(page: Page) -> list[tuple[date, float | None]]:
    """Fallback: read the visible calendar DOM directly."""
    js = r"""
    () => {
      const out = [];
      const cells = document.querySelectorAll('[data-date], [data-day-date], .mirai-day, .day');
      cells.forEach(el => {
        const d = el.getAttribute('data-date') || el.getAttribute('data-day-date');
        if (!d) return;
        const priceEl = el.querySelector('.price, [class*="price"], [class*="amount"]') || el;
        const txt = (priceEl.innerText || priceEl.textContent || '').replace(/\s+/g, ' ').trim();
        const m = txt.match(/(\d{1,4}[.,]?\d{0,2})\s*€|€\s*(\d{1,4}[.,]?\d{0,2})/);
        const price = m ? parseFloat((m[1] || m[2]).replace(',', '.')) : null;
        out.push([d, price]);
      });
      return out;
    }
    """
    raw = page.evaluate(js) or []
    rows: list[tuple[date, float | None]] = []
    for d, p in raw:
        try:
            rows.append((date.fromisoformat(d[:10]), p))
        except ValueError:
            continue
    return rows


def scrape_threehouse(ctx: BrowserContext, end_date: date) -> list[PriceRow]:
    """Walk the Mirai calendar month by month and collect daily prices."""
    today = date.today()
    targets = _months_between(today, end_date)
    captured: dict[date, tuple[float | None, bool]] = {}

    page = ctx.new_page()

    def on_response(resp):
        try:
            url = resp.url
            if "mirai.com" not in url:
                return
            if resp.status != 200:
                return
            ct = resp.headers.get("content-type", "")
            if "json" not in ct:
                return
            try:
                data = resp.json()
            except Exception:
                body = resp.text()
                if not body or body[0] not in "{[":
                    return
                data = json.loads(body)
            for d, price, avail in _iter_prices_from_json(data):
                captured.setdefault(d, (price, avail))
        except Exception as exc:
            log.debug("threehouse response hook error: %s", exc)

    page.on("response", on_response)

    log.info("threehouse: opening Mirai rates page")
    try:
        page.goto(RATES_URL, wait_until="networkidle")
    except PWTimeout:
        log.warning("threehouse: networkidle timeout, continuing")

    # Give the widget time to render the first month
    page.wait_for_timeout(2500)

    # Walk forward month by month. Mirai's "next" control varies; try multiple selectors.
    next_selectors = [
        "[aria-label*='xt']",  # next / próximo / próximo mes
        "button.next",
        ".calendar-next",
        ".mirai-calendar-next",
        "[class*='next'][class*='month']",
    ]

    months_to_advance = max(len(targets) - 1, 0)
    for i in range(months_to_advance):
        clicked = False
        for sel in next_selectors:
            try:
                locator = page.locator(sel).first
                if locator.count() and locator.is_visible():
                    locator.click(timeout=2500)
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            log.info("threehouse: could not find next-month control at step %d, stopping walk", i)
            break
        page.wait_for_timeout(1500)

    # Give hooks a final moment + do a DOM sweep as backup
    page.wait_for_timeout(1500)
    for d, p in _collect_dom_prices(page):
        captured.setdefault(d, (p, p is not None))

    page.close()

    rows: list[PriceRow] = []
    d = today
    while d <= end_date:
        price, avail = captured.get(d, (None, False))
        rows.append(
            PriceRow(
                brand=BRAND,
                hotel_name=HOTEL_NAME,
                hotel_id=HOTEL_ID,
                city=CITY,
                date=d,
                price=price,
                available=avail and price is not None,
                source_url=SOURCE_URL,
            )
        )
        d += timedelta(days=1)

    covered = sum(1 for r in rows if r.price is not None)
    log.info("threehouse: %d rows (%d with price)", len(rows), covered)
    return rows
