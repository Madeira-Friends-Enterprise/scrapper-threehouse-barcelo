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


def _iter_prices_from_json(payload: Any) -> Iterable[tuple[date, float | None, bool]]:
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            d = (
                node.get("date")
                or node.get("day")
                or node.get("checkin")
                or node.get("checkIn")
                or node.get("dia")
            )
            p = None
            for k in ("price", "rate", "minPrice", "amount", "minRate", "totalPrice", "min", "value"):
                if k in node and node[k] is not None:
                    p = node[k]
                    break
            if isinstance(p, dict):
                p = p.get("amount") or p.get("value") or p.get("gross") or p.get("min")
            if isinstance(d, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d[:10]):
                try:
                    dd = date.fromisoformat(d[:10])
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
    """Read the rendered calendar DOM. Mirai widget renders day cells with prices."""
    js = r"""
    () => {
      const out = [];
      // Try several common Mirai/calendar cell shapes.
      const cells = document.querySelectorAll(
        '[data-date], [data-day-date], [data-iso], [data-day], '
        + '.mirai-day, .day, .calendar-day, .rates-calendar__day, [class*="day-cell"]'
      );
      cells.forEach(el => {
        const d = el.getAttribute('data-date')
          || el.getAttribute('data-day-date')
          || el.getAttribute('data-iso')
          || el.getAttribute('data-day');
        if (!d) return;
        const txt = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
        const m = txt.match(/(\d{1,4}[.,]\d{1,2})\s*€|(\d{1,4})\s*€|€\s*(\d{1,4}(?:[.,]\d{1,2})?)/);
        let price = null;
        if (m) {
          const raw = m[1] || m[2] || m[3];
          price = parseFloat(raw.replace(',', '.'));
        }
        out.push([d, price]);
      });
      return out;
    }
    """
    raw = page.evaluate(js) or []
    rows: list[tuple[date, float | None]] = []
    for d, p in raw:
        try:
            rows.append((date.fromisoformat(str(d)[:10])), p) if False else None  # noqa
        except Exception:
            pass
    out: list[tuple[date, float | None]] = []
    for d, p in raw:
        try:
            out.append((date.fromisoformat(str(d)[:10]), p))
        except Exception:
            continue
    return out


def _wait_for_widget(page: Page) -> bool:
    """Wait until the Mirai widget mounts and shows day cells with text."""
    try:
        page.wait_for_function(
            """() => {
                const root = document.querySelector('[data-twin="rates"]');
                if (!root || root.children.length === 0) return false;
                // Look for any day-like element with euro text.
                const html = root.innerText || '';
                return /€/.test(html);
            }""",
            timeout=60000,
        )
        return True
    except PWTimeout:
        log.warning("threehouse: widget did not mount within 60s")
        return False


def _click_next_month(page: Page) -> bool:
    """Click whatever 'next month' control exists. Try a few variants."""
    selectors = [
        "[aria-label*='ext' i]",            # Next / Próximo / Próximo mês
        "[aria-label*='igui' i]",           # Seguinte
        "button:has-text('›')",
        "button:has-text('>')",
        "[class*='next'][class*='month']",
        ".calendar-next, .mirai-calendar-next, button.next",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=2500)
                return True
        except Exception:
            continue
    return False


def scrape_threehouse(ctx: BrowserContext, end_date: date) -> list[PriceRow]:
    today = date.today()
    months_target = (end_date.year - today.year) * 12 + (end_date.month - today.month)

    captured: dict[date, tuple[float | None, bool]] = {}
    seen_urls: list[str] = []

    page = ctx.new_page()

    def on_response(resp):
        try:
            url = resp.url
            ct = resp.headers.get("content-type", "")
            if "json" in ct or "rates" in url or "availability" in url or "calendar" in url:
                seen_urls.append(f"{resp.status} {ct[:30]} {url[:140]}")
            if resp.status != 200 or "json" not in ct:
                return
            try:
                data = resp.json()
            except Exception:
                body = resp.text()
                if not body or body[0] not in "{[":
                    return
                data = json.loads(body)
            n_before = len(captured)
            for d, price, avail in _iter_prices_from_json(data):
                captured.setdefault(d, (price, avail))
            if len(captured) > n_before:
                log.info("threehouse: +%d prices from %s", len(captured) - n_before, url[:100])
        except Exception as exc:
            log.debug("threehouse hook error: %s", exc)

    page.on("response", on_response)

    log.info("threehouse: opening Mirai rates page")
    try:
        page.goto(RATES_URL, wait_until="domcontentloaded", timeout=45000)
    except PWTimeout:
        log.warning("threehouse: domcontentloaded timeout")

    mounted = _wait_for_widget(page)
    if not mounted:
        log.warning("threehouse: widget never mounted; URLs seen (%d):", len(seen_urls))
        for u in seen_urls[:30]:
            log.warning("  %s", u)
        try:
            from pathlib import Path as _P
            _P("threehouse_dump.html").write_text(page.content(), encoding="utf-8")
        except Exception:
            pass

    # Scrape current month, then click next month until exhausted or limit hit.
    page.wait_for_timeout(2000)
    for d, p in _collect_dom_prices(page):
        captured.setdefault(d, (p, p is not None))

    for i in range(min(months_target, 24)):
        if not _click_next_month(page):
            log.info("threehouse: next-month control not found at step %d", i)
            break
        page.wait_for_timeout(2500)
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
