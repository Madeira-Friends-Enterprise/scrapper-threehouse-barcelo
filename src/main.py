from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import Counter

from .barcelo.discover import discover_barcelo_portugal
from .barcelo.scraper import scrape_all_barcelo
from .browser import playwright_context
from .config import Settings
from .models import PriceRow
from .sheets import write_rows
from .threehouse import scrape_threehouse


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Playwright is chatty at DEBUG
    logging.getLogger("playwright").setLevel(logging.WARNING)


def _summary(rows: list[PriceRow]) -> str:
    by_brand = Counter(r.brand for r in rows)
    with_price = sum(1 for r in rows if r.price is not None)
    hotels = len({(r.brand, r.hotel_id) for r in rows})
    return (
        f"{len(rows)} rows across {hotels} hotels "
        f"({with_price} with price) | per brand: {dict(by_brand)}"
    )


def cli() -> int:
    parser = argparse.ArgumentParser(description="Threehouse + Barceló PT price scraper.")
    parser.add_argument("--only", choices=["threehouse", "barcelo"], help="Limit to one brand")
    parser.add_argument("--dry-run", action="store_true", help="Scrape but don't write to Sheets")
    parser.add_argument("--rediscover", action="store_true", help="Force Barceló hotel rediscovery")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    _configure_logging(args.verbose)
    settings = Settings.load()
    log = logging.getLogger("scraper")

    rows: list[PriceRow] = []
    with playwright_context(settings) as ctx:
        if args.only in (None, "threehouse"):
            try:
                rows.extend(scrape_threehouse(ctx, settings.end_date))
            except Exception:
                log.exception("threehouse scraper crashed")

        if args.only in (None, "barcelo"):
            try:
                hotels = discover_barcelo_portugal(
                    ctx, settings.barcelo_cache_path, force=args.rediscover
                )
                if hotels:
                    rows.extend(scrape_all_barcelo(ctx, hotels, settings.end_date))
                else:
                    log.warning("barcelo: no hotels discovered, skipping")
            except Exception:
                log.exception("barcelo scraper crashed")

    log.info("done: %s", _summary(rows))

    if not rows:
        log.error("no rows scraped, nothing to write")
        return 2

    with_price = sum(1 for r in rows if r.price is not None)
    min_priced = int(os.getenv("MIN_PRICED_ROWS", "50"))
    if with_price < min_priced:
        log.error(
            "safety: only %d priced rows (< %d minimum). Refusing to overwrite sheet; prior data preserved.",
            with_price,
            min_priced,
        )
        return 2

    if args.dry_run:
        log.info("dry-run: skipping sheet write")
        for r in rows[:5]:
            log.info("sample: %s", r.to_row())
        return 0

    try:
        write_rows(settings.service_account_path, settings.sheet_id, settings.sheet_gid, rows)
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 3
    except Exception:
        log.exception("sheets write failed")
        return 4

    return 0


if __name__ == "__main__":
    sys.exit(cli())
