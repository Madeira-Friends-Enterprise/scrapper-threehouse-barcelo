from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from playwright.sync_api import Browser, BrowserContext, sync_playwright

from .config import Settings

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

STEALTH_INIT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['pt-PT', 'pt', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
window.chrome = {runtime: {}, loadTimes: () => {}, csi: () => {}, app: {}};
const origQuery = window.navigator.permissions && window.navigator.permissions.query;
if (origQuery) {
  window.navigator.permissions.query = (p) =>
    p && p.name === 'notifications'
      ? Promise.resolve({state: Notification.permission})
      : origQuery(p);
}
// WebGL spoof
const getParam = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(p) {
  if (p === 37445) return 'Intel Inc.';
  if (p === 37446) return 'Intel Iris OpenGL Engine';
  return getParam.call(this, p);
};
"""


@contextmanager
def playwright_context(settings: Settings) -> Iterator[BrowserContext]:
    with sync_playwright() as pw:
        browser: Browser = pw.chromium.launch(
            headless=settings.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-site-isolation-trials",
                "--start-maximized",
            ],
        )
        ctx = browser.new_context(
            user_agent=UA,
            locale="pt-PT",
            timezone_id="Europe/Lisbon",
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={
                "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
            },
        )
        ctx.set_default_timeout(settings.browser_timeout_ms)
        ctx.set_default_navigation_timeout(settings.browser_timeout_ms)
        ctx.add_init_script(STEALTH_INIT)
        try:
            yield ctx
        finally:
            ctx.close()
            browser.close()
