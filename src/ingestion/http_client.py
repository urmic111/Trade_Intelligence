"""HTTP helpers with retry logic for Data.gov / agency APIs."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from config.settings import HTTP_MAX_RETRIES, HTTP_RETRY_BACKOFF, HTTP_TIMEOUT

logger = logging.getLogger(__name__)


def fetch_json(
    url: str,
    params: dict[str, Any] | None = None,
    max_retries: int = HTTP_MAX_RETRIES,
    timeout: int = HTTP_TIMEOUT,
) -> Any | None:
    """GET JSON with exponential backoff. Returns None on total failure."""
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            wait = HTTP_RETRY_BACKOFF ** attempt
            logger.warning(
                "Fetch attempt %s/%s failed for %s: %s — retrying in %.1fs",
                attempt,
                max_retries,
                url,
                exc,
                wait,
            )
            time.sleep(wait)
    logger.error("All retries exhausted for %s: %s", url, last_error)
    return None


def fetch_csv_text(
    url: str,
    params: dict[str, Any] | None = None,
    max_retries: int = HTTP_MAX_RETRIES,
    timeout: int = HTTP_TIMEOUT,
) -> str | None:
    """GET text/CSV with exponential backoff."""
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            last_error = exc
            wait = HTTP_RETRY_BACKOFF ** attempt
            logger.warning(
                "CSV fetch attempt %s/%s failed for %s: %s",
                attempt,
                max_retries,
                url,
                exc,
            )
            time.sleep(wait)
    logger.error("All CSV retries exhausted for %s: %s", url, last_error)
    return None
