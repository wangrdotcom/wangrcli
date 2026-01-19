"""Arbitrage screen."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Header, Label

from wangrcli.base_screen import DataFetchingScreen


class ArbitrageScreen(DataFetchingScreen):
    """Screen displaying arbitrage opportunities."""

    BINDINGS = [("b", "go_back", "Go Back")]

    def __init__(self, data: dict) -> None:
        """Initialize arbitrage screen with data."""
        super().__init__(data)
        self.arb = data.get("arbitrage", {})

    def compose(self) -> ComposeResult:
        """Compose the screen UI."""
        yield Header()
        yield Footer()
        yield Container(id="arb-main")

    def _process_new_data(self, new_data: dict) -> None:
        """Process new data from API."""
        super()._process_new_data(new_data)
        self.arb = new_data.get("arbitrage", {})

    def _update_display(self) -> None:
        """Update the display with current data."""
        spot = self.arb.get("spot", {})
        futures = self.arb.get("futures", {})
        dex = self.arb.get("dex", {})

        # Format spot opportunity
        spot_spread = spot.get('net_spread_pct', 0)
        spot_icon = "✓" if spot_spread > 0.1 else "•"
        spot_text = f"{spot_icon} SPOT ARBITRAGE\n"
        if spot:
            spot_text += (
                f"  {spot.get('symbol', 'N/A'):12} "
                f"Buy: {spot.get('buy_exchange', 'N/A'):10} → "
                f"Sell: {spot.get('sell_exchange', 'N/A'):10}\n"
            )
            spot_text += f"  Net Spread: {spot_spread:>6.2f}%"
        else:
            spot_text += "  No opportunities"

        # Format futures opportunity
        futures_spread = futures.get('net_after_funding_pct', 0)
        futures_icon = "✓" if futures_spread > 0.1 else "•"
        futures_text = f"{futures_icon} FUTURES ARBITRAGE\n"
        if futures:
            futures_text += (
                f"  {futures.get('symbol', 'N/A'):12} "
                f"Buy: {futures.get('buy_exchange', 'N/A'):10} → "
                f"Sell: {futures.get('sell_exchange', 'N/A'):10}\n"
            )
            futures_text += (
                f"  Net Spread: {futures.get('net_spread_pct', 0):>6.2f}%  •  "
                f"After Funding: {futures_spread:>6.2f}%"
            )
        else:
            futures_text += "  No opportunities"

        # Format DEX opportunity
        dex_spread = dex.get('spread_pct', 0)
        has_arb = dex.get('arbitrage', False)
        dex_icon = "✓" if has_arb else "✗"
        dex_text = f"{'✓' if dex_spread > 0.1 else '•'} DEX ARBITRAGE\n"
        if dex:
            status = "✓ YES" if has_arb else "✗ NO"
            dex_text += (
                f"  {dex.get('token', 'N/A'):12} / {dex.get('base_token', 'N/A'):6}  "
                f"Best: {dex.get('best_dex', 'N/A'):12}\n"
            )
            dex_text += f"  Spread: {dex_spread:>6.2f}%  •  Arbitrage: {status}"
        else:
            dex_text += "  No opportunities"

        main = self.query_one("#arb-main", Container)
        main.remove_children()
        main.mount(
            Container(
                Label("⚖ Arbitrage Opportunities", classes="arb-title"),
                Label(spot_text, classes="arb-spot"),
                Label(futures_text, classes="arb-futures"),
                Label(dex_text, classes="arb-dex"),
                classes="arb-container",
            )
        )
