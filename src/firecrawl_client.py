from __future__ import annotations

import logging
import os
from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

API_URL = "https://api.firecrawl.dev/v1/scrape"
DEFAULT_TIMEOUT_S = 90


class FirecrawlError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.getenv("FIRECRAWL_API_KEY")
    if not key:
        raise FirecrawlError("FIRECRAWL_API_KEY env var is not set")
    return key


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_exception_type(FirecrawlError),
)
def scrape_markdown(
    url: str,
    actions: list[dict[str, Any]] | None = None,
    wait_for_ms: int = 3000,
    timeout_ms: int = 60000,
    only_main_content: bool = False,
) -> str:
    payload: dict[str, Any] = {
        "url": url,
        "formats": ["markdown"],
        "waitFor": wait_for_ms,
        "timeout": timeout_ms,
        "onlyMainContent": only_main_content,
    }
    if actions:
        payload["actions"] = actions

    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }

    log.info(
        "firecrawl: POST %s url=%s actions=%d waitFor=%dms",
        API_URL, url, len(actions or []), wait_for_ms,
    )
    try:
        resp = requests.post(API_URL, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT_S)
    except requests.RequestException as exc:
        raise FirecrawlError(f"network: {exc}") from exc

    if resp.status_code >= 500 or resp.status_code == 429:
        raise FirecrawlError(f"retryable status {resp.status_code}: {resp.text[:200]}")
    if not resp.ok:
        raise FirecrawlError(f"status {resp.status_code}: {resp.text[:300]}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise FirecrawlError(f"non-JSON response: {exc}") from exc

    if not data.get("success"):
        raise FirecrawlError(f"scrape failed: {data.get('error') or data}")

    md = (data.get("data") or {}).get("markdown")
    if not isinstance(md, str) or not md:
        raise FirecrawlError("empty markdown in response")

    log.info("firecrawl: ok, markdown len=%d", len(md))
    return md
