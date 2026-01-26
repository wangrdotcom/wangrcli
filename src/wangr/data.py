"""Data fetching utilities."""

import logging

from wangr.api import get_json
from wangr.config import (
    API_TIMEOUT,
    ARBITRAGE_API_URL,
    BTC_WHALES_API_URL,
    ETH_WHALES_API_URL,
    FRONTPAGE_API_URL,
    SOL_WHALES_API_URL,
    WOI_TRACKED_USERS_API_URL,
)

logger = logging.getLogger(__name__)


def fetch_dashboard_data() -> dict:
    """
    Fetch dashboard data from the API.

    Returns:
        Dictionary with dashboard data, or empty dict on error
    """
    data, err = get_json(FRONTPAGE_API_URL, timeout=API_TIMEOUT)
    if err or not isinstance(data, dict):
        logger.error("Error fetching dashboard data from %s: %s", FRONTPAGE_API_URL, err)
        return {}
    return data


def fetch_whales_full_data() -> dict:
    """
    Fetch whale data for BTC, ETH, and SOL.

    Returns:
        Dictionary with whales lists, or empty lists on error.
    """
    def fetch(url: str) -> list:
        data, err = get_json(url, timeout=API_TIMEOUT)
        if err or not isinstance(data, dict):
            logger.error("Error fetching whale data from %s: %s", url, err)
            return []
        return data.get("active_whales", [])[:30]

    return {
        "whales_btc": fetch(BTC_WHALES_API_URL),
        "whales_eth": fetch(ETH_WHALES_API_URL),
        "whales_sol": fetch(SOL_WHALES_API_URL),
    }


def fetch_woi_full_data() -> dict:
    """
    Fetch tracked WOI users.

    Returns:
        Dictionary with users list, or empty list on error.
    """
    data, err = get_json(WOI_TRACKED_USERS_API_URL, timeout=API_TIMEOUT)
    if err or not isinstance(data, dict):
        logger.error("Error fetching WOI full data from %s: %s", WOI_TRACKED_USERS_API_URL, err)
        return {"users": []}
    return {"users": data.get("users", [])}


def fetch_arbitrage_data(market: str = "futures") -> dict:
    """
    Fetch arbitrage opportunities and health for a given market.

    Args:
        market: "futures" or "spot"

    Returns:
        Dictionary with opportunities, health, and market.
    """
    prefix = "/futures" if market == "futures" else ""
    health, err = get_json(f"{ARBITRAGE_API_URL}{prefix}/health", timeout=API_TIMEOUT)
    top, err_top = get_json(
        f"{ARBITRAGE_API_URL}{prefix}/arbitrage/top",
        params={"limit": 50, "min_net_pct": -999},
        timeout=API_TIMEOUT,
    )
    if err or err_top or not isinstance(top, list):
        logger.error("Error fetching arbitrage data from %s: %s %s", ARBITRAGE_API_URL, err, err_top)
        return {"market": market, "opportunities": [], "health": None}
    return {"market": market, "opportunities": top, "health": health if isinstance(health, dict) else None}


def fetch_arbitrage_dex_data() -> dict:
    """
    Fetch DEX arbitrage data.

    Returns:
        Dictionary with base_token, amount_in_wei, pairs, and missing_pairs.
    """
    data, err = get_json(f"{ARBITRAGE_API_URL}/dex/arbitrage", timeout=API_TIMEOUT)
    if err or not isinstance(data, dict):
        logger.error("Error fetching DEX arbitrage data from %s: %s", ARBITRAGE_API_URL, err)
        return {"market": "dex", "pairs": [], "missing_pairs": []}
    return {
        "market": "dex",
        "base_token": data.get("base_token"),
        "amount_in_wei": data.get("amount_in_wei"),
        "pairs": data.get("pairs", []) or [],
        "missing_pairs": data.get("missing_pairs", []) or [],
    }


if __name__ == "__main__":
    dashboard_data = fetch_dashboard_data()
    import json

    print(json.dumps(dashboard_data, indent=2))
