"""Hyperliquid API client for fetching market data."""

import logging
from typing import Optional

from wangr.api import post_json

HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz/info"
API_TIMEOUT = 10

logger = logging.getLogger(__name__)


def fetch_prices(coins: list[str] | None = None) -> dict[str, float]:
    """
    Fetch current mark prices from Hyperliquid.

    Args:
        coins: List of coin symbols to fetch (e.g., ["BTC", "ETH", "SOL"]).
               If None, returns all available prices.

    Returns:
        Dict mapping coin symbol to price, e.g., {"BTC": 94500.0, "ETH": 3200.0}
    """
    try:
        data, err = post_json(
            HYPERLIQUID_API_URL,
            json={"type": "metaAndAssetCtxs"},
            headers={"Content-Type": "application/json"},
            timeout=API_TIMEOUT,
        )
        if err or not isinstance(data, list):
            raise ValueError(err or "Unexpected response format")

        # Response structure: [{"universe": [{"name": "BTC"}, ...]}, [{markPx: ...}, ...]]
        universe = data[0].get("universe", [])
        asset_ctxs = data[1] if len(data) > 1 else []

        prices = {}
        for i, asset in enumerate(universe):
            name = asset.get("name", "")
            if i < len(asset_ctxs):
                mark_px = asset_ctxs[i].get("markPx")
                if mark_px:
                    try:
                        prices[name] = float(mark_px)
                    except (ValueError, TypeError):
                        pass

        # Filter to requested coins if specified
        if coins:
            return {k: v for k, v in prices.items() if k in coins}
        return prices

    except (ValueError, KeyError, IndexError) as e:
        logger.error(f"Error parsing Hyperliquid response: {e}")
        return {}


def fetch_asset_context(coin: str) -> Optional[dict]:
    """
    Fetch full asset context for a single coin.

    Args:
        coin: Coin symbol (e.g., "BTC")

    Returns:
        Asset context dict with markPx, funding, openInterest, etc.
    """
    try:
        data, err = post_json(
            HYPERLIQUID_API_URL,
            json={"type": "metaAndAssetCtxs"},
            headers={"Content-Type": "application/json"},
            timeout=API_TIMEOUT,
        )
        if err or not isinstance(data, list):
            raise ValueError(err or "Unexpected response format")

        universe = data[0].get("universe", [])
        asset_ctxs = data[1] if len(data) > 1 else []

        for i, asset in enumerate(universe):
            if asset.get("name") == coin and i < len(asset_ctxs):
                return asset_ctxs[i]

        return None

    except ValueError as e:
        logger.error(f"Error fetching asset context from Hyperliquid: {e}")
        return None


def fetch_funding_history(coin: str, start_time_ms: int, end_time_ms: int | None = None) -> list[dict]:
    """
    Fetch historical funding rates for a coin.

    Args:
        coin: Coin symbol (e.g., "BTC")
        start_time_ms: Start time in milliseconds
        end_time_ms: End time in milliseconds (defaults to now)

    Returns:
        List of funding rate records with coin, fundingRate, premium, time
    """
    try:
        payload = {
            "type": "fundingHistory",
            "coin": coin,
            "startTime": start_time_ms,
        }
        if end_time_ms:
            payload["endTime"] = end_time_ms

        data, err = post_json(
            HYPERLIQUID_API_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=API_TIMEOUT,
        )
        if err or not isinstance(data, list):
            raise ValueError(err or "Unexpected response format")
        return data

    except ValueError as e:
        logger.error(f"Error fetching funding history from Hyperliquid: {e}")
        return []


def fetch_all_asset_contexts() -> tuple[list[dict], list[dict]]:
    """
    Fetch universe and all asset contexts.

    Returns:
        Tuple of (universe list, asset contexts list)
    """
    try:
        data, err = post_json(
            HYPERLIQUID_API_URL,
            json={"type": "metaAndAssetCtxs"},
            headers={"Content-Type": "application/json"},
            timeout=API_TIMEOUT,
        )
        if err or not isinstance(data, list):
            raise ValueError(err or "Unexpected response format")

        universe = data[0].get("universe", [])
        asset_ctxs = data[1] if len(data) > 1 else []

        return universe, asset_ctxs

    except ValueError as e:
        logger.error(f"Error fetching asset contexts from Hyperliquid: {e}")
        return [], []
