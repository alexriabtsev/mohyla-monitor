"""Polite HTTP: honest User-Agent, timeouts, small retry with backoff.

We never disguise the client. If a site refuses us (401/403/429 after retries),
the caller gets a FetchError and must degrade gracefully, not work around it.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

DEFAULT_UA = "MohylaMonitor/0.1 (media monitoring of NaUKMA community)"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    def __init__(self, url: str, reason: str):
        super().__init__(f"{url}: {reason}")
        self.url = url
        self.reason = reason


def make_client(user_agent: str = DEFAULT_UA, timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": user_agent},
        timeout=timeout,
        follow_redirects=True,
    )


def fetch(
    client: httpx.Client,
    url: str,
    *,
    method: str = "GET",
    retries: int = 2,
    backoff: float = 2.0,
    **kwargs: Any,
) -> httpx.Response:
    """Return a 2xx response or raise FetchError. Retries only transient statuses."""
    last_reason = "unknown"
    for attempt in range(retries + 1):
        try:
            resp = client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            last_reason = f"{type(exc).__name__}: {exc}"
        else:
            if resp.is_success:
                return resp
            last_reason = f"HTTP {resp.status_code}"
            if resp.status_code not in RETRY_STATUSES:
                break
        if attempt < retries:
            time.sleep(backoff * (attempt + 1))
    log.warning("fetch failed %s (%s)", url, last_reason)
    raise FetchError(url, last_reason)
