"""Data fetching utilities."""

import json
import logging

import requests

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
    try:
        response = requests.get(FRONTPAGE_API_URL, timeout=API_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error fetching data from {FRONTPAGE_API_URL}: {e}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON from {FRONTPAGE_API_URL}: {e}")
        return {}


def fetch_whales_full_data() -> dict:
    """
    Fetch whale data for BTC, ETH, and SOL.

    Returns:
        Dictionary with whales lists, or empty lists on error.
    """
    def fetch(url: str) -> list:
        try:
            resp = requests.get(url, timeout=API_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            return data.get("active_whales", [])[:30]
        except requests.RequestException as e:
            logger.error(f"Error fetching whale data from {url}: {e}")
            return []
        except ValueError as e:
            logger.error(f"Error parsing JSON from {url}: {e}")
            return []

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
    try:
        resp = requests.get(WOI_TRACKED_USERS_API_URL, timeout=API_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return {"users": data.get("users", [])}
    except requests.RequestException as e:
        logger.error(f"Error fetching WOI full data from {WOI_TRACKED_USERS_API_URL}: {e}")
        return {"users": []}


def fetch_arbitrage_data(market: str = "futures") -> dict:
    """
    Fetch arbitrage opportunities and health for a given market.

    Args:
        market: "futures" or "spot"

    Returns:
        Dictionary with opportunities, health, and market.
    """
    prefix = "/futures" if market == "futures" else ""
    try:
        health_resp = requests.get(f"{ARBITRAGE_API_URL}{prefix}/health", timeout=API_TIMEOUT)
        top_resp = requests.get(
            f"{ARBITRAGE_API_URL}{prefix}/arbitrage/top",
            params={"limit": 50, "min_net_pct": -999},
            timeout=API_TIMEOUT,
        )
        if not health_resp.ok or not top_resp.ok:
            return {"market": market, "opportunities": [], "health": None}
        return {
            "market": market,
            "opportunities": top_resp.json(),
            "health": health_resp.json(),
        }
    except requests.RequestException as e:
        logger.error(f"Error fetching arbitrage data from {ARBITRAGE_API_URL}: {e}")
        return {"market": market, "opportunities": [], "health": None}


def fetch_arbitrage_dex_data() -> dict:
    """
    Fetch DEX arbitrage data.

    Returns:
        Dictionary with base_token, amount_in_wei, pairs, and missing_pairs.
    """
    try:
        resp = requests.get(f"{ARBITRAGE_API_URL}/dex/arbitrage", timeout=API_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return {
            "market": "dex",
            "base_token": data.get("base_token"),
            "amount_in_wei": data.get("amount_in_wei"),
            "pairs": data.get("pairs", []) or [],
            "missing_pairs": data.get("missing_pairs", []) or [],
        }
    except requests.RequestException as e:
        logger.error(f"Error fetching DEX arbitrage data from {ARBITRAGE_API_URL}: {e}")
        return {"market": "dex", "pairs": [], "missing_pairs": []}
    except ValueError as e:
        logger.error(f"Error parsing DEX JSON from {ARBITRAGE_API_URL}: {e}")
        return {"market": "dex", "pairs": [], "missing_pairs": []}
    except ValueError as e:
        logger.error(f"Error parsing JSON from {ARBITRAGE_API_URL}: {e}")
        return {"market": market, "opportunities": [], "health": None}
    except ValueError as e:
        logger.error(f"Error parsing JSON from {WOI_TRACKED_USERS_API_URL}: {e}")
        return {"users": []}


if __name__ == "__main__":
    dashboard_data = fetch_dashboard_data()
    print(json.dumps(dashboard_data, indent=2))
