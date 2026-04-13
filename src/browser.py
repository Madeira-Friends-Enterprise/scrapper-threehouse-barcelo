from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from playwright.sync_api import Browser, BrowserContext, Playwright, sync_playwright

from .config import Settings

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36"
)


@contextmanager
def playwright_context(settings: Settings) -> Iterator[BrowserContext]:
    with sync_playwright() as pw:
        browser: Browser = pw.chromium.launch(
            headless=settings.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        ctx = browser.new_context(
            user_agent=UA,
            locale="pt-PT",
            timezone_id="Europe/Lisbon",
            viewport={"width": 1440, "height": 900},
            extra_http_headers={
                "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
            },
        )
        ctx.set_default_timeout(settings.browser_timeout_ms)
        ctx.set_default_navigation_timeout(settings.browser_timeout_ms)
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        try:
            yield ctx
        finally:
            ctx.close()
            browser.close()
