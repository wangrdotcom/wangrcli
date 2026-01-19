"""Liquidations screen."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Header, Label

from wangr.base_screen import DataFetchingScreen
from wangr.config import MILLION
from wangr.utils import format_bar, safe_division


class LiquidationsScreen(DataFetchingScreen):
    """Screen displaying liquidation statistics."""

    BINDINGS = [("b", "go_back", "Go Back")]

    def __init__(self, data: dict) -> None:
        """Initialize liquidations screen with data."""
        super().__init__(data)
        self.liqs = data.get("liquidations", {})

    def compose(self) -> ComposeResult:
        """Compose the screen UI."""
        yield Header()
        yield Footer()
        yield Container(id="liq-main")

    def _process_new_data(self, new_data: dict) -> None:
        """Process new data from API."""
        super()._process_new_data(new_data)
        self.liqs = new_data.get("liquidations", {})

    def _update_display(self) -> None:
        """Update the display with current data."""
        total_24h = safe_division(self.liqs.get("total_usd_24h", 0), MILLION)
        long_24h = safe_division(self.liqs.get("total_long_usd_24h", 0), MILLION)
        short_24h = safe_division(self.liqs.get("total_short_usd_24h", 0), MILLION)
        long_count = self.liqs.get("long_count_24h", 0)
        short_count = self.liqs.get("short_count_24h", 0)

        by_exchange = self.liqs.get("by_exchange", {})
        largest_24h = self.liqs.get("largest_24h", {})
        largest_long = self.liqs.get("largest_long_all_time", {})
        largest_short = self.liqs.get("largest_short_all_time", {})

        # Build exchange breakdown with short format bars
        exchange_text = "By Exchange (24h):\n"
        name_width = max((len(name) for name in by_exchange.keys()), default=0) + 1
        for name, data in by_exchange.items():
            l_usd = safe_division(data.get("long_total_usd", 0), MILLION)
            s_usd = safe_division(data.get("short_total_usd", 0), MILLION)
            bar = format_bar(f"↑{l_usd:.1f}M", f"↓{s_usd:.1f}M", l_usd, s_usd, width=16)
            exchange_text += f"  {name.upper():{name_width}} {bar}\n"

        # Build largest liquidations
        largest_text = "Largest Liquidations:\n"
        largest_text += (
            f"  24h:       {largest_24h.get('coin', 'N/A'):3} "
            f"{largest_24h.get('side', 'N/A'):5} "
            f"${safe_division(largest_24h.get('value_usd', 0), MILLION):>6.2f}M\n"
        )
        largest_text += (
            f"  ATH Long:  {largest_long.get('coin', 'N/A'):3} "
            f"{largest_long.get('side', 'N/A'):5} "
            f"${safe_division(largest_long.get('value_usd', 0), MILLION):>6.2f}M\n"
        )
        largest_text += (
            f"  ATH Short: {largest_short.get('coin', 'N/A'):3} "
            f"{largest_short.get('side', 'N/A'):5} "
            f"${safe_division(largest_short.get('value_usd', 0), MILLION):>6.2f}M"
        )

        main = self.query_one("#liq-main", Container)
        main.remove_children()
        main.mount(
            Container(
                Label("💧 Liquidations (24h)", classes="liq-title"),
                Label(
                    f"Total: ${total_24h:.2f}M  •  "
                    f"↑ ${long_24h:.2f}M ({long_count})  •  "
                    f"↓ ${short_24h:.2f}M ({short_count})",
                    classes="liq-summary"
                ),
                Label(
                    format_bar(f"↑ ${long_24h:.1f}M", f"↓ ${short_24h:.1f}M", long_24h, short_24h),
                    classes="liq-bar"
                ),
                Label(
                    format_bar(f"↑ {long_count}", f"↓ {short_count}", long_count, short_count),
                    classes="liq-bar"
                ),
                Label(exchange_text, classes="liq-exchanges"),
                Label(largest_text, classes="liq-largest"),
                classes="liq-container",
            )
        )
