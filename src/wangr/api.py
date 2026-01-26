"""Shared API helpers for JSON HTTP requests."""

from __future__ import annotations

import logging
from typing import Any

import requests

from wangr.config import API_TIMEOUT

logger = logging.getLogger(__name__)

_session = requests.Session()


class ApiError(RuntimeError):
    """Raised when a JSON API request fails."""


def request_json(
    method: str,
    url: str,
    *,
    params: dict | None = None,
    json: dict | None = None,
    headers: dict | None = None,
    timeout: int | float = API_TIMEOUT,
) -> tuple[Any | None, str | None]:
    """Request JSON and return (data, error_message)."""
    try:
        resp = _session.request(
            method,
            url,
            params=params,
            json=json,
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json(), None
    except requests.RequestException as exc:
        logger.error("HTTP error for %s %s: %s", method.upper(), url, exc)
        return None, str(exc)
    except ValueError as exc:
        logger.error("JSON parse error for %s %s: %s", method.upper(), url, exc)
        return None, str(exc)


def get_json(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int | float = API_TIMEOUT,
) -> tuple[Any | None, str | None]:
    """GET JSON and return (data, error_message)."""
    return request_json("GET", url, params=params, headers=headers, timeout=timeout)


def post_json(
    url: str,
    *,
    params: dict | None = None,
    json: dict | None = None,
    headers: dict | None = None,
    timeout: int | float = API_TIMEOUT,
) -> tuple[Any | None, str | None]:
    """POST JSON and return (data, error_message)."""
    return request_json(
        "POST",
        url,
        params=params,
        json=json,
        headers=headers,
        timeout=timeout,
    )


def get_json_or_raise(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int | float = API_TIMEOUT,
) -> Any:
    """GET JSON and raise ApiError on failure."""
    data, err = get_json(url, params=params, headers=headers, timeout=timeout)
    if err or data is None:
        raise ApiError(err or f"Failed GET {url}")
    return data


def post_json_or_raise(
    url: str,
    *,
    params: dict | None = None,
    json: dict | None = None,
    headers: dict | None = None,
    timeout: int | float = API_TIMEOUT,
) -> Any:
    """POST JSON and raise ApiError on failure."""
    data, err = post_json(
        url,
        params=params,
        json=json,
        headers=headers,
        timeout=timeout,
    )
    if err or data is None:
        raise ApiError(err or f"Failed POST {url}")
    return data
