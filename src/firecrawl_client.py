from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

API_URL = "https://api.firecrawl.dev/v1/scrape"
BATCH_URL = "https://api.firecrawl.dev/v1/batch/scrape"
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
        # Render from an EUR-zone IP so the Mirai widget serves Portuguese
        # hotels in euros. "PT" breaks the widget (renders K-notation with no
        # currency); ES/FR/DE all produce € cleanly. ES is the closest geo.
        "location": {"country": "ES"},
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


def scrape_batch_markdown(
    urls: list[str],
    actions: list[dict[str, Any]] | None = None,
    wait_for_ms: int = 3000,
    timeout_ms: int = 60000,
    poll_interval_s: float = 8.0,
    max_wait_s: int = 1800,
) -> dict[str, str]:
    """Submit `urls` to Firecrawl's batch endpoint, poll until done, return
    {url: markdown}. Failed URLs are silently omitted (caller treats as None).

    Batch executes URLs in parallel server-side; total wall-clock for ~200
    Booking URLs is typically 5-10 min vs ~50 min serial.
    """
    if not urls:
        return {}

    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "urls": urls,
        "formats": ["markdown"],
        "waitFor": wait_for_ms,
        "timeout": timeout_ms,
        "onlyMainContent": False,
        "location": {"country": "ES"},
    }
    if actions:
        payload["actions"] = actions

    log.info("firecrawl: BATCH POST %d urls", len(urls))
    try:
        resp = requests.post(BATCH_URL, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT_S)
    except requests.RequestException as exc:
        raise FirecrawlError(f"batch submit network: {exc}") from exc
    if not resp.ok:
        raise FirecrawlError(f"batch submit {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    job_id = data.get("id")
    poll_url = data.get("url") or f"{BATCH_URL}/{job_id}"
    if not job_id:
        raise FirecrawlError(f"batch missing id: {data}")
    log.info("firecrawl: batch id=%s polling=%s", job_id, poll_url)

    out: dict[str, str] = {}
    started = time.time()
    next_skip = 0
    while True:
        elapsed = int(time.time() - started)
        if elapsed > max_wait_s:
            log.warning(
                "firecrawl: batch %s timed out after %ds (got %d/%d so far)",
                job_id, elapsed, len(out), len(urls),
            )
            break
        try:
            r = requests.get(
                poll_url,
                headers=headers,
                timeout=DEFAULT_TIMEOUT_S,
                params={"skip": next_skip} if next_skip else None,
            )
        except requests.RequestException as exc:
            log.warning("firecrawl: batch poll network err %s; retrying", exc)
            time.sleep(poll_interval_s)
            continue
        if not r.ok:
            log.warning("firecrawl: batch poll %d: %s", r.status_code, r.text[:200])
            time.sleep(poll_interval_s)
            continue
        d = r.json()
        for item in d.get("data") or []:
            md = item.get("markdown") or ""
            url = (item.get("metadata") or {}).get("sourceURL") or (item.get("metadata") or {}).get("url")
            if url and md:
                out[url] = md
        next_skip = len(out)
        status = d.get("status")
        completed = d.get("completed", len(out))
        total = d.get("total", len(urls))
        log.info(
            "firecrawl: batch %s status=%s %d/%d (elapsed=%ds)",
            job_id, status, completed, total, elapsed,
        )
        if status == "completed":
            break
        if status in ("failed", "cancelled"):
            log.warning("firecrawl: batch %s ended %s with %d results", job_id, status, len(out))
            break
        time.sleep(poll_interval_s)

    log.info("firecrawl: batch %s done, captured %d/%d", job_id, len(out), len(urls))
    return out
