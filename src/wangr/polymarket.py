"""Polymarket screen."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Header, Label

from wangr.base_screen import DataFetchingScreen
from wangr.config import MILLION, THOUSAND
from wangr.utils import format_bar, safe_division


class PolymarketScreen(DataFetchingScreen):
    """Screen displaying Polymarket trader statistics."""

    BINDINGS = [("b", "go_back", "Go Back")]

    def __init__(self, data: dict) -> None:
        """Initialize Polymarket screen with data."""
        super().__init__(data)
        self.poly = data.get("polymarket", {})

    def compose(self) -> ComposeResult:
        """Compose the screen UI."""
        yield Header()
        yield Footer()
        yield Container(id="poly-main")

    def _process_new_data(self, new_data: dict) -> None:
        """Process new data from API."""
        super()._process_new_data(new_data)
        self.poly = new_data.get("polymarket", {})

    def _update_display(self) -> None:
        """Update the display with current data."""
        traders = self.poly.get("traders_tracked", 0)
        whales = self.poly.get("whale_count", 0)
        super_traders = self.poly.get("super_trader_count", 0)

        total_port = safe_division(self.poly.get("total_portfolio_value", 0), MILLION)
        mean_port = self.poly.get("mean_portfolio_value", 0)
        median_port = self.poly.get("median_portfolio_value", 0)

        total_pnl = safe_division(self.poly.get("total_pnl", 0), MILLION)
        mean_pnl = self.poly.get("mean_pnl", 0)
        median_pnl = self.poly.get("median_pnl", 0)

        profitable = self.poly.get("profitable_count", 0)
        losing = self.poly.get("losing_count", 0)
        profit_pct = self.poly.get("profitable_pct", 0)

        mean_wr = self.poly.get("mean_win_rate", 0)
        median_wr = self.poly.get("median_win_rate", 0)
        total_vol = safe_division(self.poly.get("total_recent_volume", 0), MILLION)

        top_port = self.poly.get("top_3_by_portfolio", [])
        top_pnl = self.poly.get("top_3_by_pnl", [])
        top_wr = self.poly.get("top_3_by_win_rate", [])

        # Build top traders text
        traders_text = "💼 Top by Portfolio:\n"
        for t in top_port[:3]:
            wallet = t.get("wallet", "")
            port = safe_division(t.get("portfolio_value", 0), MILLION)
            pnl = safe_division(t.get("total_pnl", 0), MILLION)
            traders_text += f"  • {wallet} ${port:>5.2f}M (PnL: ${pnl:>+5.2f}M)\n"

        traders_text += "💰 Top by PnL:\n"
        for t in top_pnl[:3]:
            wallet = t.get("wallet", "")
            pnl = safe_division(t.get("total_pnl", 0), MILLION)
            port = safe_division(t.get("portfolio_value", 0), THOUSAND)
            traders_text += f"  • {wallet} ${pnl:>5.2f}M (Port: ${port:>6.1f}k)\n"

        traders_text += "🏆 Top by Win Rate:\n"
        for t in top_wr[:3]:
            wallet = t.get("wallet", "")
            wr = t.get("win_rate", 0)
            pos = t.get("positions_count", 0)
            pnl = safe_division(t.get("total_pnl", 0), THOUSAND)
            traders_text += f"  • {wallet} {wr:>5.1f}% ({pos:>3}pos) PnL:${pnl:>+6.1f}k\n"

        main = self.query_one("#poly-main", Container)
        main.remove_children()
        main.mount(
            Container(
                Label("📈 Polymarket", classes="poly-title"),
                Label(
                    f"Traders: {traders:,}  •  "
                    f"🐋 {whales}  •  "
                    f"⭐ {super_traders}  •  "
                    f"Vol: ${total_vol:.1f}M",
                    classes="poly-summary"
                ),
                Label(
                    f"Portfolio - Total: ${total_port:.2f}M  •  "
                    f"Mean: ${mean_port:,.0f}  •  "
                    f"Median: ${median_port:.0f}",
                    classes="poly-stats"
                ),
                Label(
                    f"PnL - Total: ${total_pnl:.2f}M  •  "
                    f"Mean: ${mean_pnl:,.0f}  •  "
                    f"Median: ${median_pnl:.0f}",
                    classes="poly-stats"
                ),
                Label(
                    format_bar(
                        f"✓ {profitable} ({profit_pct:.1f}%)",
                        f"✗ {losing} ({100-profit_pct:.1f}%)",
                        profitable,
                        losing
                    ),
                    classes="poly-bar"
                ),
                Label(
                    f"Win Rate - Mean: {mean_wr:.1f}%  •  Median: {median_wr:.1f}%",
                    classes="poly-stats"
                ),
                Label(traders_text, classes="poly-traders"),
                classes="poly-container",
            )
        )
