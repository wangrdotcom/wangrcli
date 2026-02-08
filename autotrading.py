#!/usr/bin/env python3
"""
autotrading.py

Lightweight whale-following autotrader (Wangr)

What this script does
- Polls a Wangr-compatible whale API for the top N whales on a symbol.
- Generates simple follow signals when a whale opens or increases a position.
- Optionally executes orders through an exchange connector (ccxt) or runs in dry-run mode.

Important safety notes
- This is example code. Do NOT run with real API keys until you have audited and tested it.
- Default mode is DRY_RUN (no real orders).
- You are responsible for compliance and risk controls.

Configuration (via environment variables)
- WG_API_BASE: base URL for the Wangr-style whale API (default: https://api.wangr.example)
- WG_API_KEY: optional API key to fetch private endpoints
- SYMBOL: e.g. BTC, ETH, SOL
- FOLLOW_LIMIT: number of top whales to follow (default 5)
- POLL_INTERVAL: seconds between polls (default 10)
- DRY_RUN: if '1' or 'true', do not send real orders (default 'true')
- EXCHANGE: 'ccxt' exchange id (e.g. 'binance') if auto-execution is desired
- EXCHANGE_API_KEY, EXCHANGE_API_SECRET: credentials for exchange (required for live)

Run:
    python autotrading.py

Dependencies: requests, ccxt (optional), python-dotenv (optional)
"""

import os
import time
import logging
import requests
from typing import Dict, List, Any

try:
    import ccxt
except Exception:
    ccxt = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Config
WG_API_BASE = os.getenv("WG_API_BASE", "https://api.wangr.example")
WG_API_KEY = os.getenv("WG_API_KEY", "")
SYMBOL = os.getenv("SYMBOL", "btc").lower()
FOLLOW_LIMIT = int(os.getenv("FOLLOW_LIMIT", "5"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))
DRY_RUN = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")

# Execution / risk params
EXCHANGE_ID = os.getenv("EXCHANGE", "") or None
EXCHANGE_API_KEY = os.getenv("EXCHANGE_API_KEY")
EXCHANGE_API_SECRET = os.getenv("EXCHANGE_API_SECRET")
MAX_POSITION_USD = float(os.getenv("MAX_POSITION_USD", "1000"))  # max notional per mirrored trade
MIRROR_FRACTION = float(os.getenv("MIRROR_FRACTION", "0.02"))  # fraction of whale notional to mirror
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.03"))  # 3% stop by default

HEADERS = {"Accept": "application/json"}
if WG_API_KEY:
    HEADERS["Authorization"] = f"Bearer {WG_API_KEY}"


def fetch_top_whales(symbol: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Fetch top whales by size from the configured Wangr endpoint.

    The endpoint and returned JSON must match the contract:
      GET {WG_API_BASE}/whales/top?coin={symbol}&limit={limit}

    Returns a list of whale dicts with at least: wallet, side, size, entry_price, leverage, unrealized_pnl, liquidation_price
    """
    url = f"{WG_API_BASE.rstrip('/')}/whales/top"
    params = {"coin": symbol, "limit": limit}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
        # flexible: accept either {whales: [...]} or [...]
        if isinstance(data, dict) and "whales" in data:
            return data["whales"]
        if isinstance(data, list):
            return data
        logging.warning("Unexpected whales payload format")
        return []
    except Exception as e:
        logging.error("Failed fetching whales: %s", e)
        return []


class ExchangeExecutor:
    def __init__(self, exchange_id: str, api_key: str, api_secret: str):
        if ccxt is None:
            raise RuntimeError("ccxt required for live execution. Install ccxt or run in DRY_RUN mode.")
        self.x = getattr(ccxt, exchange_id)({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
        })

    def place_market_order(self, symbol: str, side: str, amount: float):
        # symbol should be exchange format (e.g., 'BTC/USDT')
        logging.info("Placing market %s %s %s", side, symbol, amount)
        return self.x.create_market_order(symbol, side, amount)

    def create_stop_loss(self, symbol: str, side: str, amount: float, stop_price: float):
        # Exchange-specific; this is a placeholder using create_order
        params = {"stopPrice": stop_price}
        logging.info("Creating stop %s %s %s @%s", side, symbol, amount, stop_price)
        return self.x.create_order(symbol, "STOP_MARKET", side, amount, None, params)


def build_symbol_for_exchange(coin: str) -> str:
    # Basic mapping to USDT pair
    return f"{coin.upper()}/USDT"


def compute_trade_size_from_whale(whale: Dict[str, Any]) -> Dict[str, Any]:
    """Decide how much to mirror based on whale notional or size.

    Expects whale to contain either 'notional' in USD or 'size' (coin qty) and 'entry_price'.
    Returns: dict with keys: side, amount_coin, notional_usd
    """
    side = whale.get("side") or whale.get("position_side") or "long"
    entry = float(whale.get("entry_price") or whale.get("entryPrice") or 0) or 0.0
    size = whale.get("notional") or whale.get("size")
    # if size is token quantity, convert to notional
    try:
        size = float(size)
    except Exception:
        size = 0.0

    if whale.get("notional"):
        notional = float(whale["notional"])
        amount_coin = notional / max(entry, 1e-8)
    else:
        amount_coin = size
        notional = amount_coin * entry

    mirror_notional = min(notional * MIRROR_FRACTION, MAX_POSITION_USD)
    amount_to_place = mirror_notional / max(entry, 1e-8) if entry > 0 else 0.0
    if side.lower() in ("short", "sell"):
        side_use = "sell"
    else:
        side_use = "buy"

    return {"side": side_use, "amount_coin": amount_to_place, "notional_usd": mirror_notional}


def main():
    logging.info("Starting Wangr whale follower (symbol=%s) DRY_RUN=%s", SYMBOL, DRY_RUN)

    executor = None
    if not DRY_RUN:
        if not EXCHANGE_ID or not EXCHANGE_API_KEY or not EXCHANGE_API_SECRET:
            logging.error("Live mode requires EXCHANGE, EXCHANGE_API_KEY and EXCHANGE_API_SECRET environment variables")
            return
        executor = ExchangeExecutor(EXCHANGE_ID, EXCHANGE_API_KEY, EXCHANGE_API_SECRET)

    tracked = {}  # wallet -> last observed position signature

    while True:
        whales = fetch_top_whales(SYMBOL, FOLLOW_LIMIT)
        if not whales:
            time.sleep(POLL_INTERVAL)
            continue

        for w in whales:
            wallet = w.get("wallet") or w.get("address") or "unknown"
            side = (w.get("side") or "long").lower()
            size = float(w.get("size") or w.get("notional") or 0) or 0.0
            entry = float(w.get("entry_price") or w.get("entryPrice") or 0) or 0.0
            liq = float(w.get("liquidation_price") or w.get("liquidationPrice") or 0) or 0.0

            # signature used to detect changes (side + size rounded)
            sig = f"{side}:{round(size,6)}:{round(entry,2)}"
            prev_sig = tracked.get(wallet)
            if prev_sig != sig:
                logging.info("Detected change for whale %s side=%s size=%s entry=%s liq=%s", wallet, side, size, entry, liq)

                # simple rule: if whale opens/increases position -> mirror a small fraction
                tt = compute_trade_size_from_whale(w)
                symbol_pair = build_symbol_for_exchange(SYMBOL)
                logging.info("Signal: mirror %s %s (approx notional $%s) based on whale %s", tt["side"], round(tt["amount_coin"],6), round(tt["notional_usd"],2), wallet)

                if tt["amount_coin"] > 0.00001:
                    if DRY_RUN:
                        logging.info("DRY_RUN enabled — not placing order")
                    else:
                        try:
                            res = executor.place_market_order(symbol_pair, tt["side"], tt["amount_coin"])
                            logging.info("Order result: %s", res)
                            # place stop loss
                            if STOP_LOSS_PCT and tt["notional_usd"] > 0:
                                stop_price = entry * (1 - STOP_LOSS_PCT) if tt["side"] == "buy" else entry * (1 + STOP_LOSS_PCT)
                                logging.info("Placing stop loss @ %s", stop_price)
                                try:
                                    executor.create_stop_loss(symbol_pair, "sell" if tt["side"]=="buy" else "buy", tt["amount_coin"], stop_price)
                                except Exception as e:
                                    logging.warning("Failed to create stop loss: %s", e)
                        except Exception as e:
                            logging.error("Order failed: %s", e)

                tracked[wallet] = sig

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Stopped by user")
