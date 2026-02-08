"""Shared NDJSON streaming helpers for agent chat screens."""

import json
import re
from typing import Any, Generator

import requests

from wangr.config import API_TIMEOUT
from wangr.settings import get_api_key

_STATUS_SUPPRESS = re.compile(
    r"error|exception|\d{3}\s+(Client|Server)", re.IGNORECASE
)


def should_suppress_status(message: str) -> bool:
    """Return True if the status message should be hidden from the user."""
    return bool(_STATUS_SUPPRESS.search(message))


def stream_post(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: int | float = API_TIMEOUT * 12,
) -> requests.Response:
    """POST with streaming enabled, injecting auth headers."""
    headers = {"Content-Type": "application/json"}
    api_key = get_api_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    response = requests.post(
        url, json=payload, headers=headers, timeout=timeout, stream=True
    )
    response.raise_for_status()
    return response


def iter_ndjson_events(
    response: requests.Response,
) -> Generator[dict[str, Any], None, None]:
    """Yield parsed JSON events from an NDJSON streaming response."""
    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.strip():
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue
