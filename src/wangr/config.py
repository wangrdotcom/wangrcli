"""Configuration constants for the TUI Dashboard."""

from typing import Final

# API URLs
FRONTPAGE_API_URL: Final[str] = "https://polymarket-api.wangr.com/frontpage/"
PMARKETS_BASE_URL: Final[str] = "https://pmarkets.wangr.com"
BTC_WHALES_API_URL: Final[str] = "https://api3.wangr.com/whales"
ETH_WHALES_API_URL: Final[str] = "https://ethwhalesapi.wangr.com/whales"
SOL_WHALES_API_URL: Final[str] = "https://solwhalesapi.wangr.com/whales"
CHAT_API_URL: Final[str] = "https://cliagent.wangr.com/chat"
WOI_TRACKED_USERS_API_URL: Final[str] = "https://api2899.wangr.com/woi/tracked-users?limit=400"
POLYMARKET_WHALES_API_URL: Final[str] = "https://polymarket-api.wangr.com/whales"
POLYMARKET_TRADER_API_URL: Final[str] = "https://polymarket-api.wangr.com/trader"
ARBITRAGE_API_URL: Final[str] = "https://arbitrage.wangr.com"

# Timeouts
API_TIMEOUT: Final[int] = 10
FETCH_INTERVAL: Final[float] = 60.0

# Display Constants
BAR_WIDTH: Final[int] = 50
PRICE_FORMAT_THRESHOLD: Final[int] = 20000

# Numeric Constants
MILLION: Final[int] = 1_000_000
THOUSAND: Final[int] = 1_000
