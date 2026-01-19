"""Wallets of Interest screen."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Header, Label

from wangrcli.base_screen import DataFetchingScreen
from wangrcli.config import MILLION
from wangrcli.utils import format_bar, format_time, safe_division


class WOIScreen(DataFetchingScreen):
    """Screen displaying Wallets of Interest statistics."""

    BINDINGS = [("b", "go_back", "Go Back")]

    def __init__(self, data: dict) -> None:
        """Initialize WOI screen with data."""
        super().__init__(data)
        self.woi = data.get("woi", {})

    def compose(self) -> ComposeResult:
        """Compose the screen UI."""
        yield Header()
        yield Footer()
        yield Container(id="woi-main")

    def _process_new_data(self, new_data: dict) -> None:
        """Process new data from API."""
        super()._process_new_data(new_data)
        self.woi = new_data.get("woi", {})

    def _update_display(self) -> None:
        """Update the display with current data."""
        agg = self.woi.get("aggregates", {})
        top_wr = self.woi.get("top_3_by_win_rate", [])
        top_pnl = self.woi.get("top_3_by_pnl", [])

        # Build top wallets text
        wallets_text = "🏆 Top by Win Rate:\n"
        for w in top_wr[:3]:
            wallet = w.get("wallet", "")
            wr = w.get("win_rate", 0)
            pnl = safe_division(w.get("total_realized_pnl", 0), MILLION)
            wallets_text += f"  • {wallet} {wr:>3.0f}% ${pnl:>6.2f}M\n"

        wallets_text += "💰 Top by PnL:\n"
        for w in top_pnl[:3]:
            wallet = w.get("wallet", "")
            wr = w.get("win_rate", 0)
            pnl = safe_division(w.get("total_realized_pnl", 0), MILLION)
            wallets_text += f"  • {wallet} {wr:>3.0f}% ${pnl:>6.2f}M\n"

        # Safely calculate metrics
        total_pnl = safe_division(agg.get('total_realized_pnl', 0), MILLION)
        avg_pnl = safe_division(agg.get('average_pnl', 0), 1000)  # in thousands

        main = self.query_one("#woi-main", Container)
        main.remove_children()
        main.mount(
            Container(
                Label("👛 Wallets of Interest", classes="woi-title"),
                Label(
                    f"PnL: ${total_pnl:.2f}M  •  "
                    f"Win: {agg.get('win_share', 0):.1f}%  •  "
                    f"Trades: {agg.get('total_trades', 0)}",
                    classes="woi-summary"
                ),
                Label(
                    format_bar(
                        f"↑ {agg.get('long_count', 0)}",
                        f"↓ {agg.get('short_count', 0)}",
                        agg.get('long_count', 0),
                        agg.get('short_count', 0)
                    ),
                    classes="woi-bar"
                ),
                Label(
                    f"⏱ Avg: {format_time(agg.get('average_hold_minutes', 0))}  •  "
                    f"Avg PnL: ${avg_pnl:.1f}k  •  "
                    f"Min: {format_time(agg.get('min_hold_minutes', 0))}  •  "
                    f"Max: {format_time(agg.get('max_hold_minutes', 0))}",
                    classes="woi-stats"
                ),
                Label(wallets_text, classes="woi-wallets"),
                classes="woi-container",
            )
        )
