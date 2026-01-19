"""Market Brief screen showing coin prices and sentiment."""

from textual.app import ComposeResult
from textual.containers import Container, HorizontalGroup, VerticalScroll
from textual.widgets import Digits, Footer, Header, Label

from wangrcli.base_screen import DataFetchingScreen
from wangrcli.utils import safe_float


class CoinPrices(Container):
    """Container displaying coin prices and 24h changes."""

    def __init__(self, data: dict) -> None:
        """Initialize with coin data."""
        super().__init__()
        btc = data.get("btc", {})
        eth = data.get("eth", {})
        sol = data.get("sol", {})

        # Safely convert prices to strings for Digits widget
        self.btc_price = str(safe_float(btc.get("price"), 0))
        self.btc_change_24h_pct = safe_float(btc.get("change_24h_pct"), 0.0)
        self.eth_price = str(safe_float(eth.get("price"), 0))
        self.eth_change_24h_pct = safe_float(eth.get("change_24h_pct"), 0.0)
        self.sol_price = str(safe_float(sol.get("price"), 0))
        self.sol_change_24h_pct = safe_float(sol.get("change_24h_pct"), 0.0)

    def compose(self) -> ComposeResult:
        """Compose the coin prices display."""
        btc_change_class = "change-positive" if self.btc_change_24h_pct >= 0 else "change-negative"
        eth_change_class = "change-positive" if self.eth_change_24h_pct >= 0 else "change-negative"
        sol_change_class = "change-positive" if self.sol_change_24h_pct >= 0 else "change-negative"

        btc_arrow = "▲" if self.btc_change_24h_pct >= 0 else "▼"
        eth_arrow = "▲" if self.eth_change_24h_pct >= 0 else "▼"
        sol_arrow = "▲" if self.sol_change_24h_pct >= 0 else "▼"

        yield HorizontalGroup(
            Label("₿"),
            Label(f"{btc_arrow} {self.btc_change_24h_pct:+.2f}%", classes=btc_change_class),
            Digits(self.btc_price),
            Label("Ξ"),
            Label(f"{eth_arrow} {self.eth_change_24h_pct:+.2f}%", classes=eth_change_class),
            Digits(self.eth_price),
            Label("◎"),
            Label(f"{sol_arrow} {self.sol_change_24h_pct:+.2f}%", classes=sol_change_class),
            Digits(self.sol_price),
        )


class SentimentInfo(Container):
    """Container displaying sentiment analysis."""

    def __init__(self, data: dict) -> None:
        """Initialize with sentiment data."""
        super().__init__()
        self.sentiment = data.get("value", "N/A")
        self.post_count = data.get("post_count", 0)
        self.summary = data.get("summary", "")
        self.bullish_summary = data.get("bullish_summary", "")
        self.bearish_summary = data.get("bearish_summary", "")

    def compose(self) -> ComposeResult:
        """Compose the sentiment display."""
        # Determine sentiment icon
        sentiment_lower = str(self.sentiment).lower()
        if "bullish" in sentiment_lower or "positive" in sentiment_lower:
            sentiment_icon = "🟢"
        elif "bearish" in sentiment_lower or "negative" in sentiment_lower:
            sentiment_icon = "🔴"
        else:
            sentiment_icon = "🟡"

        yield Label(f"{sentiment_icon} Sentiment: {self.sentiment}")
        yield Label(f"📊 Posts: {self.post_count}")
        yield Label("Summary:")
        yield Label(self.summary, classes="summary-text")
        yield Label("🟢 Bullish:", classes="bullish-label")
        yield Label(self.bullish_summary, classes="bullish-text")
        yield Label("🔴 Bearish:", classes="bearish-label")
        yield Label(self.bearish_summary, classes="bearish-text")


class MarketBriefScreen(DataFetchingScreen):
    """Screen displaying market brief with prices and sentiment."""

    BINDINGS = [("b", "go_back", "Go Back")]

    def compose(self) -> ComposeResult:
        """Compose the screen UI."""
        yield Header()
        yield Footer()
        yield VerticalScroll(
            CoinPrices(self.data),
            SentimentInfo(self.data.get("sentiment", {})),
            id="content-scroll"
        )

    def _update_display(self) -> None:
        """Update the display with new data."""
        scroll = self.query_one("#content-scroll", VerticalScroll)
        scroll.remove_children()
        scroll.mount(CoinPrices(self.data))
        scroll.mount(SentimentInfo(self.data.get("sentiment", {})))
