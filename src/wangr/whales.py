"""Whales screen showing whale position statistics."""

from textual.app import ComposeResult
from textual import events
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.widgets import Footer, Header, Label, Static

from wangr.base_screen import DataFetchingScreen
from wangr.config import MILLION, THOUSAND
from wangr.utils import format_bar, safe_division, safe_float


class WhalesScreen(DataFetchingScreen):
    """Screen displaying whale position statistics across BTC, ETH, and SOL."""

    BINDINGS = [
        ("b", "go_back", "Go Back"),
        ("left,h,shift+tab", "prev_coin", "Previous"),
        ("right,l,tab", "next_coin", "Next"),
    ]

    selected_coin: reactive[str] = reactive("BTC")

    def __init__(self, data: dict) -> None:
        """Initialize whales screen with data."""
        super().__init__(data)
        self.whales_btc = data.get("whales", {})
        self.whales_eth = data.get("whales_eth", {})
        self.whales_sol = data.get("whales_sol", {})
        self.btc_price = safe_float(data.get("btc", {}).get("price"), 0)
        self.eth_price = safe_float(data.get("eth", {}).get("price"), 0)
        self.sol_price = safe_float(data.get("sol", {}).get("price"), 0)

    def _metric(self, label: str, lval: str, lpct: str, sval: str, spct: str) -> str:
        """Format a metric with colored percentage indicators."""
        lpct_colored = lpct
        spct_colored = spct

        # Color code percentages - check if not empty string
        if lpct and len(lpct) > 0:
            color = "green" if lpct.startswith("+") else "red" if lpct.startswith("-") else "white"
            lpct_colored = f"[{color}]{lpct}[/{color}]"
        if spct and len(spct) > 0:
            color = "green" if spct.startswith("+") else "red" if spct.startswith("-") else "white"
            spct_colored = f"[{color}]{spct}[/{color}]"

        return f"{label:12} L {lval:>8} {lpct_colored:>15}  S {sval:>8} {spct_colored:>15}"

    def _get_current_price(self) -> float:
        """Get the current price for the selected coin."""
        if self.selected_coin == "BTC":
            return self.btc_price
        elif self.selected_coin == "ETH":
            return self.eth_price
        else:
            return self.sol_price

    def _get_current_whales(self) -> dict:
        """Get the whale data for the selected coin."""
        if self.selected_coin == "BTC":
            return self.whales_btc
        elif self.selected_coin == "ETH":
            return self.whales_eth
        else:
            return self.whales_sol

    def _calc_long_pnl_pct(self, entry: float) -> str:
        """Calculate PnL percentage for long positions."""
        price = self._get_current_price()
        if entry == 0 or price == 0:
            return ""
        pct = safe_division(price - entry, entry) * 100
        return f"{pct:+.1f}%"

    def _calc_short_pnl_pct(self, entry: float) -> str:
        """Calculate PnL percentage for short positions."""
        price = self._get_current_price()
        if entry == 0 or price == 0:
            return ""
        pct = safe_division(entry - price, entry) * 100
        return f"{pct:+.1f}%"

    def _calc_liq_pct(self, liq_price: float) -> str:
        """Calculate liquidation price distance percentage."""
        price = self._get_current_price()
        if price == 0 or liq_price == 0:
            return ""
        pct = safe_division(liq_price - price, price) * 100
        return f"{pct:+.1f}%"

    def compose(self) -> ComposeResult:
        """Compose the screen UI."""
        yield Header()
        yield Footer()
        yield Horizontal(
            Static("₿ BTC", id="coin-btc", classes="coin-toggle coin-toggle-active"),
            Static("Ξ ETH", id="coin-eth", classes="coin-toggle"),
            Static("◎ SOL", id="coin-sol", classes="coin-toggle"),
            id="whale-coins",
        )
        yield Container(
            Label("", id="whale-title", classes="whale-title"),
            Label("", id="whale-bar-1", classes="whale-bar"),
            Label("", id="whale-bar-2", classes="whale-bar"),
            Label("", id="whale-bar-3", classes="whale-bar"),
            Label("", id="whale-metric-1", classes="whale-metric"),
            Label("", id="whale-metric-2", classes="whale-metric"),
            Label("", id="whale-metric-3", classes="whale-metric"),
            Label("", id="whale-metric-4", classes="whale-metric"),
            Label("", id="whale-metric-5", classes="whale-metric"),
            Label("", id="whale-positions", classes="whale-positions"),
            id="whale-content"
        )

    def _process_new_data(self, new_data: dict) -> None:
        """Process new data from API."""
        super()._process_new_data(new_data)
        self.whales_btc = new_data.get("whales", {})
        self.whales_eth = new_data.get("whales_eth", {})
        self.whales_sol = new_data.get("whales_sol", {})
        self.btc_price = safe_float(new_data.get("btc", {}).get("price"), 0)
        self.eth_price = safe_float(new_data.get("eth", {}).get("price"), 0)
        self.sol_price = safe_float(new_data.get("sol", {}).get("price"), 0)
        self._update_coin_classes(self.selected_coin)

    def watch_selected_coin(self, new_coin: str) -> None:
        """React to coin selection changes."""
        self._update_coin_classes(new_coin)
        self._update_display()

    def _update_display(self) -> None:
        """Update the display with current whale data."""
        w = self._get_current_whales()
        coin_label = self.selected_coin
        coin_symbols = {"BTC": "₿", "ETH": "Ξ", "SOL": "◎"}
        coin_sym = coin_symbols.get(coin_label, "")

        # Build whale tables text
        whale_text = "↑ Top Longs:\n"
        for p in w.get("top_3_longs", [])[:3]:
            wlt = p.get("wallet", "")[:12]
            sz = p.get("size_btc", 0)
            lv = p.get("leverage", 0)
            pnl = safe_division(p.get("unrealized_pnl", 0), MILLION)
            whale_text += f"  {wlt}… {sz:>7.0f}{coin_sym}({lv:>2}x) ${pnl:>+6.2f}M\n"

        whale_text += "↓ Top Shorts:\n"
        for p in w.get("top_3_shorts", [])[:3]:
            wlt = p.get("wallet", "")[:12]
            sz = p.get("size_btc", 0)
            lv = p.get("leverage", 0)
            pnl = safe_division(p.get("unrealized_pnl", 0), MILLION)
            whale_text += f"  {wlt}… {sz:>7.0f}{coin_sym}({lv:>2}x) ${pnl:>+6.2f}M\n"

        # Safely calculate values
        long_notional = safe_division(w.get('long_notional_usd', 0), MILLION)
        short_notional = safe_division(w.get('short_notional_usd', 0), MILLION)
        mean_long_entry_k = safe_division(w.get('mean_long_entry', 0), THOUSAND)
        mean_short_entry_k = safe_division(w.get('mean_short_entry', 0), THOUSAND)
        median_long_entry_k = safe_division(w.get('median_long_entry', 0), THOUSAND)
        median_short_entry_k = safe_division(w.get('median_short_entry', 0), THOUSAND)
        mean_long_liq_k = safe_division(w.get('mean_long_liq', 0), THOUSAND)
        mean_short_liq_k = safe_division(w.get('mean_short_liq', 0), THOUSAND)

        # Update existing labels
        self.query_one("#whale-title", Label).update(
            f"🐋 Whales: {w.get('count', 0)} • {w.get('total_btc', 0):,.0f} {coin_sym}"
        )
        self.query_one("#whale-bar-1", Label).update(
            format_bar(
                f"↑ {w.get('long_count', 0)}",
                f"↓ {w.get('short_count', 0)}",
                w.get('long_count', 0),
                w.get('short_count', 0)
            )
        )
        self.query_one("#whale-bar-2", Label).update(
            format_bar(
                f"↑ {w.get('long_size_btc', 0):,.0f}{coin_sym}",
                f"↓ {w.get('short_size_btc', 0):,.0f}{coin_sym}",
                w.get('long_size_btc', 0),
                w.get('short_size_btc', 0)
            )
        )
        self.query_one("#whale-bar-3", Label).update(
            format_bar(
                f"↑ ${long_notional:.0f}M",
                f"↓ ${short_notional:.0f}M",
                w.get('long_notional_usd', 0),
                w.get('short_notional_usd', 0)
            )
        )
        self.query_one("#whale-metric-1", Label).update(
            self._metric(
                "Med Size",
                f"{w.get('median_long_btc', 0):.0f}",
                "",
                f"{w.get('median_short_btc', 0):.0f}",
                ""
            )
        )
        self.query_one("#whale-metric-2", Label).update(
            self._metric(
                "Mean Entry",
                f"${mean_long_entry_k:.1f}k",
                self._calc_long_pnl_pct(w.get('mean_long_entry', 0)),
                f"${mean_short_entry_k:.1f}k",
                self._calc_short_pnl_pct(w.get('mean_short_entry', 0))
            )
        )
        self.query_one("#whale-metric-3", Label).update(
            self._metric(
                "Med Entry",
                f"${median_long_entry_k:.1f}k",
                self._calc_long_pnl_pct(w.get('median_long_entry', 0)),
                f"${median_short_entry_k:.1f}k",
                self._calc_short_pnl_pct(w.get('median_short_entry', 0))
            )
        )
        self.query_one("#whale-metric-4", Label).update(
            self._metric(
                "Liq Price",
                f"${mean_long_liq_k:.1f}k",
                self._calc_liq_pct(w.get('mean_long_liq', 0)),
                f"${mean_short_liq_k:.1f}k",
                self._calc_liq_pct(w.get('mean_short_liq', 0))
            )
        )
        self.query_one("#whale-metric-5", Label).update(
            self._metric(
                "Mean Lev",
                f"{w.get('mean_long_leverage', 0):.1f}x",
                "",
                f"{w.get('mean_short_leverage', 0):.1f}x",
                ""
            )
        )
        self.query_one("#whale-positions", Label).update(whale_text)

    def action_prev_coin(self) -> None:
        """Navigate to previous coin."""
        if self.selected_coin == "BTC":
            self.selected_coin = "SOL"
        elif self.selected_coin == "ETH":
            self.selected_coin = "BTC"
        else:
            self.selected_coin = "ETH"

    def action_next_coin(self) -> None:
        """Navigate to next coin."""
        if self.selected_coin == "BTC":
            self.selected_coin = "ETH"
        elif self.selected_coin == "ETH":
            self.selected_coin = "SOL"
        else:
            self.selected_coin = "BTC"

    def on_click(self, event: events.Click) -> None:
        """Handle coin selection via mouse."""
        target = event.widget
        if not isinstance(target, Static):
            return
        if target.id == "coin-btc":
            self.selected_coin = "BTC"
        elif target.id == "coin-eth":
            self.selected_coin = "ETH"
        elif target.id == "coin-sol":
            self.selected_coin = "SOL"

    def _update_coin_classes(self, new_coin: str) -> None:
        """Update coin label styles based on selection."""
        mapping = {
            "BTC": "#coin-btc",
            "ETH": "#coin-eth",
            "SOL": "#coin-sol",
        }
        for key, selector in mapping.items():
            label = self.query_one(selector, Static)
            if key == new_coin:
                label.add_class("coin-toggle-active")
            else:
                label.remove_class("coin-toggle-active")
