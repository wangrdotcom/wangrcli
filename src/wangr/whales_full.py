"""Whales full screen with sortable DataTable."""

import logging
from functools import partial
from typing import Optional

import requests
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, Static
from textual.worker import Worker

from wangr.config import (
    API_TIMEOUT,
    BTC_WHALES_API_URL,
    ETH_WHALES_API_URL,
    FETCH_INTERVAL,
    MILLION,
    SOL_WHALES_API_URL,
    THOUSAND,
)
from wangr.hyperliquid import fetch_prices
from wangr.sort_modal import SortModal
from wangr.sparkline import mini_bar
from wangr.utils import format_price, safe_division, safe_float

logger = logging.getLogger(__name__)


class WhalesFullScreen(Screen):
    """Screen displaying sortable whale positions across BTC, ETH, and SOL."""

    BINDINGS = [
        ("b", "go_back", "Go Back"),
        ("left,h", "prev_coin", "Previous"),
        ("right,l", "next_coin", "Next"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("up", "cursor_up", "Up"),
        ("s", "sort_by_column", "Sort Column"),
        ("S", "toggle_sort_direction", "Toggle Sort"),
        ("ctrl+d", "page_down", "Page Down"),
        ("ctrl+u", "page_up", "Page Up"),
        ("G", "cursor_bottom", "Bottom"),
    ]

    COLUMN_DEFS = [
        ("wallet", "Wallet"),
        ("side", "Side"),
        ("size", "Size"),
        ("entry", "Entry"),
        ("lev", "Lev"),
        ("upnl_usd", "uPnL (USD)"),
        ("upnl_pct", "uPnL (%)"),
        ("rpnl", "rPnL (USD)"),
        ("wr", "Win Rate"),
        ("trades", "Trades"),
        ("liq", "Liquidation"),
    ]

    selected_coin: reactive[str] = reactive("BTC")

    def __init__(self, data: dict, cache: dict | None = None) -> None:
        """Initialize whales full screen with data."""
        super().__init__()
        self.data = data
        # Detailed whale lists (from dedicated APIs)
        self.whales_btc = []
        self.whales_eth = []
        self.whales_sol = []
        if cache:
            self.whales_btc = cache.get("whales_btc", [])
            self.whales_eth = cache.get("whales_eth", [])
            self.whales_sol = cache.get("whales_sol", [])
        # Summary stats (from frontpage API)
        self.summary_btc = data.get("whales", {})
        self.summary_eth = data.get("whales_eth", {})
        self.summary_sol = data.get("whales_sol", {})
        # Prices
        self.btc_price = safe_float(data.get("btc", {}).get("price"), 0)
        self.eth_price = safe_float(data.get("eth", {}).get("price"), 0)
        self.sol_price = safe_float(data.get("sol", {}).get("price"), 0)
        # Sort state
        self.sort_column = None
        self.sort_reverse = False
        # Timers and workers
        self.update_timer = None
        self._btc_worker: Optional[Worker] = None
        self._eth_worker: Optional[Worker] = None
        self._sol_worker: Optional[Worker] = None
        self._price_worker: Optional[Worker] = None
        self._pending_g = False
        self._g_timer = None

    def _get_current_price(self) -> float:
        """Get the current price for the selected coin."""
        if self.selected_coin == "BTC":
            return self.btc_price
        elif self.selected_coin == "ETH":
            return self.eth_price
        else:
            return self.sol_price

    def _get_current_whales(self) -> list:
        """Get the whale data for the selected coin."""
        if self.selected_coin == "BTC":
            return self.whales_btc or []
        elif self.selected_coin == "ETH":
            return self.whales_eth or []
        else:
            return self.whales_sol or []

    def _get_current_summary(self) -> dict:
        """Get the summary stats for the selected coin."""
        if self.selected_coin == "BTC":
            return self.summary_btc
        elif self.selected_coin == "ETH":
            return self.summary_eth
        else:
            return self.summary_sol

    def _color_pct(self, pct: str) -> str:
        """Color a percentage string - bright colors for dark background."""
        if not pct:
            return ""
        # Use brighter colors: lime green and coral/salmon for better contrast
        if pct.startswith("+"):
            return f"[#90EE90]{pct}[/#90EE90]"  # Light green
        elif pct.startswith("-"):
            return f"[#FF6B6B]{pct}[/#FF6B6B]"  # Light coral
        return pct

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

    def _build_price_ladder(self) -> str:
        """Build a vertical price ladder visualization showing entries and liquidations relative to current price."""
        w = self._get_current_summary()
        price = self._get_current_price()

        if price == 0:
            return "Price data unavailable"

        # Get prices
        mean_long_entry = w.get('mean_long_entry', 0)
        mean_short_entry = w.get('mean_short_entry', 0)
        mean_long_liq = w.get('mean_long_liq', 0)
        mean_short_liq = w.get('mean_short_liq', 0)

        def pct_from_price(p: float) -> float:
            if p == 0:
                return 0
            return safe_division(p - price, price) * 100

        def format_price_k(p: float) -> str:
            if p >= THOUSAND:
                return f"${p / THOUSAND:.1f}k"
            return f"${p:.1f}"

        def color_pct(pct: float) -> str:
            if pct > 0:
                return f"[#FF6B6B]{pct:+.1f}%[/#FF6B6B]"  # Red/coral for above price
            elif pct < 0:
                return f"[#90EE90]{pct:+.1f}%[/#90EE90]"  # Green for below price
            return "0.0%"

        # Build price points: (label, price_value, is_current)
        points = [
            ("Short Liq", mean_short_liq, False),
            ("Short Entry", mean_short_entry, False),
            ("CURRENT", price, True),
            ("Long Entry", mean_long_entry, False),
            ("Long Liq", mean_long_liq, False),
        ]

        # Filter out zero prices and sort by price descending
        points = [(label, p, is_curr) for label, p, is_curr in points if p > 0]
        points.sort(key=lambda x: x[1], reverse=True)

        lines = []
        for i, (label, p, is_current) in enumerate(points):
            price_str = format_price_k(p)
            if is_current:
                lines.append(f"  {price_str:>8}  ┤[bold]━━━ {label} ━━━[/bold]")
            else:
                pct = pct_from_price(p)
                pct_str = color_pct(pct)
                lines.append(f"  {price_str:>8}  ┤ ▸ {label} ({pct_str})")

            # Add spacing line between points (except after last)
            if i < len(points) - 1:
                lines.append("            │")

        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        """Compose the screen UI."""
        yield Header()
        yield Footer()
        yield Horizontal(
            Static("₿ BTC", id="coin-btc", classes="coin-toggle coin-toggle-active"),
            Static("Ξ ETH", id="coin-eth", classes="coin-toggle"),
            Static("◎ SOL", id="coin-sol", classes="coin-toggle"),
            id="whalefull-coins",
        )
        # Summary section - two columns
        yield Container(
            Label("", id="whale-title", classes="whale-title"),
            Horizontal(
                # Left column: COUNT, SIZE, NOTIONAL, MEDIAN
                Container(
                    Label("COUNT", classes="whale-section-header"),
                    Label("", id="whale-count-long", classes="whale-bar-stacked"),
                    Label("", id="whale-count-short", classes="whale-bar-stacked"),
                    Label("SIZE", classes="whale-section-header"),
                    Label("", id="whale-size-long", classes="whale-bar-stacked"),
                    Label("", id="whale-size-short", classes="whale-bar-stacked"),
                    Label("NOTIONAL", classes="whale-section-header"),
                    Label("", id="whale-notional-long", classes="whale-bar-stacked"),
                    Label("", id="whale-notional-short", classes="whale-bar-stacked"),
                    Label("MEDIAN POSITION", classes="whale-section-header"),
                    Label("", id="whale-median-long", classes="whale-bar-stacked"),
                    Label("", id="whale-median-short", classes="whale-bar-stacked"),
                    id="whale-left-col",
                ),
                # Right column: PRICE LADDER
                Container(
                    Label("", id="whale-price-ladder", classes="whale-metric"),
                    Label("", id="whale-leverage"),
                    id="whale-right-col",
                ),
                id="whale-columns",
            ),
            id="whale-summary",
        )
        yield DataTable(id="whales-table", zebra_stripes=True, cursor_type="row")

    def _fetch_whale_data(self, url: str) -> list:
        """Fetch whale data from API."""
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

    async def on_mount(self) -> None:
        """Mount handler - start data fetching."""
        self._update_summary_display()
        self._update_whale_display()
        self.query_one("#whales-table", DataTable).focus()
        self._update_coin_classes(self.selected_coin)

        self._fetch_all_whale_data()
        self.update_timer = self.set_interval(FETCH_INTERVAL, self._fetch_all_whale_data)

    def on_unmount(self) -> None:
        """Unmount handler - cleanup resources."""
        if self.update_timer:
            self.update_timer.stop()
            self.update_timer = None
        if self._g_timer:
            self._g_timer.stop()
            self._g_timer = None

        # Cancel all workers to prevent memory leak
        if self._btc_worker and self._btc_worker.is_running:
            self._btc_worker.cancel()
        if self._eth_worker and self._eth_worker.is_running:
            self._eth_worker.cancel()
        if self._sol_worker and self._sol_worker.is_running:
            self._sol_worker.cancel()
        if self._price_worker and self._price_worker.is_running:
            self._price_worker.cancel()
        self._update_cache()

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

    def _fetch_all_whale_data(self) -> None:
        """Fetch whale data and prices for all coins in parallel."""
        # Fetch whale data
        if self._btc_worker and self._btc_worker.is_running:
            logger.debug("BTC worker still running, skipping fetch")
        else:
            self._btc_worker = self.run_worker(
                partial(self._fetch_whale_data, BTC_WHALES_API_URL),
                name="btc",
                thread=True,
            )

        if self._eth_worker and self._eth_worker.is_running:
            logger.debug("ETH worker still running, skipping fetch")
        else:
            self._eth_worker = self.run_worker(
                partial(self._fetch_whale_data, ETH_WHALES_API_URL),
                name="eth",
                thread=True,
            )

        if self._sol_worker and self._sol_worker.is_running:
            logger.debug("SOL worker still running, skipping fetch")
        else:
            self._sol_worker = self.run_worker(
                partial(self._fetch_whale_data, SOL_WHALES_API_URL),
                name="sol",
                thread=True,
            )

        # Fetch prices from Hyperliquid
        if self._price_worker and self._price_worker.is_running:
            logger.debug("Price worker still running, skipping fetch")
        else:
            self._price_worker = self.run_worker(
                partial(fetch_prices, ["BTC", "ETH", "SOL"]),
                name="prices",
                thread=True,
            )

    def on_worker_state_changed(self, event) -> None:
        """Handle worker completion."""
        if event.state.name == "SUCCESS":
            if event.worker.name == "btc":
                self.whales_btc = event.worker.result
                self._update_whale_display()
                self._update_cache()
            elif event.worker.name == "eth":
                self.whales_eth = event.worker.result
                self._update_whale_display()
                self._update_cache()
            elif event.worker.name == "sol":
                self.whales_sol = event.worker.result
                self._update_whale_display()
                self._update_cache()
            elif event.worker.name == "prices":
                prices = event.worker.result
                if prices:
                    self.btc_price = prices.get("BTC", self.btc_price)
                    self.eth_price = prices.get("ETH", self.eth_price)
                    self.sol_price = prices.get("SOL", self.sol_price)
                    self._update_summary_display()
                    self._update_whale_display()

    def watch_selected_coin(self, new_coin: str) -> None:
        """React to coin selection changes."""
        self._update_coin_classes(new_coin)
        self._update_summary_display()
        self._update_whale_display()

    def _stacked_bar(self, label: str, value: float, max_val: float, value_str: str, width: int = 30) -> str:
        """Create a stacked bar line: 'Long   ████████████  1,200'."""
        bar = mini_bar(value, max_val, width=width)
        return f"  {label:<6} {bar}  {value_str}"

    def _update_summary_display(self) -> None:
        """Update the summary stats display."""
        w = self._get_current_summary()
        coin_symbols = {"BTC": "₿", "ETH": "Ξ", "SOL": "◎"}
        coin_sym = coin_symbols.get(self.selected_coin, "")

        # Get values
        long_count = w.get('long_count', 0)
        short_count = w.get('short_count', 0)
        long_size = w.get('long_size_btc', 0)
        short_size = w.get('short_size_btc', 0)
        long_notional = safe_division(w.get('long_notional_usd', 0), MILLION)
        short_notional = safe_division(w.get('short_notional_usd', 0), MILLION)

        # Update title
        self.query_one("#whale-title", Label).update(
            f"🐋 Whales: {w.get('count', 0)} • {w.get('total_btc', 0):,.0f} {coin_sym}"
        )

        # Count bars (scaled to max of both)
        count_max = max(long_count, short_count, 1)
        self.query_one("#whale-count-long", Label).update(
            self._stacked_bar("Long", long_count, count_max, str(long_count))
        )
        self.query_one("#whale-count-short", Label).update(
            self._stacked_bar("Short", short_count, count_max, str(short_count))
        )

        # Size bars
        size_max = max(long_size, short_size, 1)
        self.query_one("#whale-size-long", Label).update(
            self._stacked_bar("Long", long_size, size_max, f"{long_size:,.0f}{coin_sym}")
        )
        self.query_one("#whale-size-short", Label).update(
            self._stacked_bar("Short", short_size, size_max, f"{short_size:,.0f}{coin_sym}")
        )

        # Notional bars
        notional_max = max(long_notional, short_notional, 1)
        self.query_one("#whale-notional-long", Label).update(
            self._stacked_bar("Long", long_notional, notional_max, f"${long_notional:.0f}M")
        )
        self.query_one("#whale-notional-short", Label).update(
            self._stacked_bar("Short", short_notional, notional_max, f"${short_notional:.0f}M")
        )

        # Median position size bars (in left column)
        median_long = w.get('median_long_btc', 0)
        median_short = w.get('median_short_btc', 0)
        median_max = max(median_long, median_short, 1)
        self.query_one("#whale-median-long", Label).update(
            self._stacked_bar("Long", median_long, median_max, f"{median_long:.0f}{coin_sym}")
        )
        self.query_one("#whale-median-short", Label).update(
            self._stacked_bar("Short", median_short, median_max, f"{median_short:.0f}{coin_sym}")
        )

        # Price ladder visualization (in right column)
        price_ladder = self._build_price_ladder()
        self.query_one("#whale-price-ladder", Label).update(
            f"PRICE LADDER\n{price_ladder}"
        )

        # Mean leverage info
        self.query_one("#whale-leverage", Label).update(
            f"  Mean Lev  Long {w.get('mean_long_leverage', 0):.1f}x  Short {w.get('mean_short_leverage', 0):.1f}x"
        )

    def _update_whale_display(self) -> None:
        """Update the display with current whale data."""
        whales = self._get_current_whales()
        price = self._get_current_price()

        table = self.query_one("#whales-table", DataTable)
        table.clear(columns=True)

        # Add columns
        for key, label in self.COLUMN_DEFS:
            table.add_column(label, key=key)

        if not whales:
            table.add_row(
                "Loading...",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            )
            return

        whales = [whale for whale in whales if isinstance(whale, dict)]

        # Sort whales if a column is selected
        if self.sort_column:
            whales = self._sort_whales(whales, price)

        # Add rows
        for whale in whales:
            pos = whale.get("position") or {}
            stats = whale.get("initial_stats") or {}

            wallet = whale.get("wallet", "")
            side = whale.get("side", "")
            size = safe_float(whale.get("size"), 0)
            entry = safe_float(pos.get("entry_px"), 0)
            upnl = safe_division(pos.get("unrealized_pnl", 0), MILLION)
            lev = pos.get("leverage_value", 0)
            liq_raw = pos.get("liquidation_px")
            liq = safe_float(liq_raw, 0) if liq_raw else None

            rpnl = safe_division(stats.get("total_realized_pnl", 0), MILLION)
            wr = safe_float(stats.get("win_rate"), 0)
            trades = stats.get("total_trades", 0)

            # Calculate PnL %
            is_long = side == "LONG"
            if entry > 0 and price > 0:
                if is_long:
                    pnl_pct = safe_division(price - entry, entry) * 100
                else:
                    pnl_pct = safe_division(entry - price, entry) * 100
            else:
                pnl_pct = 0

            # Format entry price
            entry_text = format_price(entry)

            # Format liquidation
            if liq and liq > 0:
                liq_text = format_price(liq)
                if price > 0:
                    liq_dist = safe_division(liq - price, price) * 100
                    liq_text += f" ({liq_dist:+.1f}%)"
            else:
                liq_text = "N/A"

            # Format side with arrow
            side_icon = "↑" if is_long else "↓"
            side_display = f"{side_icon} {side}"

            table.add_row(
                wallet,
                side_display,
                f"{size:.1f}",
                entry_text,
                f"{lev}x",
                f"${upnl:+.2f}M",
                f"{pnl_pct:+.1f}%",
                f"${rpnl:+.2f}M",
                f"{wr:.1f}%",
                str(trades),
                liq_text,
            )

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

    def _sort_whales(self, whales: list, price: float) -> list:
        """Sort whales by the selected column."""

        def get_sort_key(whale: dict):
            pos = whale.get("position") or {}
            stats = whale.get("initial_stats") or {}

            if self.sort_column == "wallet":
                return whale.get("wallet", "")
            elif self.sort_column == "side":
                return whale.get("side", "")
            elif self.sort_column == "size":
                return safe_float(whale.get("size"), 0)
            elif self.sort_column == "entry":
                return safe_float(pos.get("entry_px"), 0)
            elif self.sort_column == "lev":
                return pos.get("leverage_value", 0)
            elif self.sort_column == "upnl_usd":
                return safe_division(pos.get("unrealized_pnl", 0), MILLION)
            elif self.sort_column == "upnl_pct":
                entry = safe_float(pos.get("entry_px"), 0)
                side = whale.get("side", "")
                if entry > 0 and price > 0:
                    if side == "LONG":
                        return safe_division(price - entry, entry) * 100
                    else:
                        return safe_division(entry - price, entry) * 100
                return 0
            elif self.sort_column == "rpnl":
                return safe_division(stats.get("total_realized_pnl", 0), MILLION)
            elif self.sort_column == "wr":
                return safe_float(stats.get("win_rate"), 0)
            elif self.sort_column == "trades":
                return stats.get("total_trades", 0)
            elif self.sort_column == "liq":
                liq_raw = pos.get("liquidation_px")
                return safe_float(liq_raw, 0) if liq_raw else 0
            return 0

        return sorted(whales, key=get_sort_key, reverse=self.sort_reverse)

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Handle column header clicks for sorting."""
        if self.sort_column == event.column_key.value:
            # Toggle sort direction if clicking same column
            self.sort_reverse = not self.sort_reverse
        else:
            # New column, default to descending
            self.sort_column = event.column_key.value
            self.sort_reverse = True

        self._update_whale_display()

    def action_go_back(self) -> None:
        """Go back to previous screen."""
        self.app.pop_screen()

    def action_cursor_down(self) -> None:
        """Move table cursor down."""
        self.query_one("#whales-table", DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move table cursor up."""
        self.query_one("#whales-table", DataTable).action_cursor_up()

    def action_page_down(self) -> None:
        """Move table cursor one page down."""
        self.query_one("#whales-table", DataTable).action_page_down()

    def action_page_up(self) -> None:
        """Move table cursor one page up."""
        self.query_one("#whales-table", DataTable).action_page_up()

    def action_cursor_top(self) -> None:
        """Move table cursor to top."""
        table = self.query_one("#whales-table", DataTable)
        if table.row_count > 0:
            table.move_cursor(row=0)

    def action_cursor_bottom(self) -> None:
        """Move table cursor to bottom."""
        table = self.query_one("#whales-table", DataTable)
        if table.row_count > 0:
            table.move_cursor(row=table.row_count - 1)
    def action_sort_by_column(self) -> None:
        """Open sort dialog."""
        self.app.push_screen(
            SortModal(self.COLUMN_DEFS, self.sort_column, self.sort_reverse),
            self._on_sort_selected,
        )

    def action_toggle_sort_direction(self) -> None:
        """Toggle current sort direction."""
        if self.sort_column is None:
            self.sort_column = self.COLUMN_DEFS[0][0]
        self.sort_reverse = not self.sort_reverse
        self._update_whale_display()

    def on_key(self, event: events.Key) -> None:
        """Handle vim-style gg jump."""
        if event.key == "g":
            event.prevent_default()
            if self._pending_g:
                self._pending_g = False
                if self._g_timer:
                    self._g_timer.stop()
                    self._g_timer = None
                self.action_cursor_top()
            else:
                self._pending_g = True
                if self._g_timer:
                    self._g_timer.stop()
                self._g_timer = self.set_timer(0.5, self._clear_pending_g)
        else:
            self._clear_pending_g()

    def _clear_pending_g(self) -> None:
        """Clear pending g state."""
        self._pending_g = False
        if self._g_timer:
            self._g_timer.stop()
            self._g_timer = None

    def _on_sort_selected(self, result: dict | None) -> None:
        """Apply sort selection from modal."""
        if not result:
            return
        self.sort_column = result.get("key")
        self.sort_reverse = result.get("reverse", self.sort_reverse)
        self._update_whale_display()

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

    def _update_cache(self) -> None:
        """Cache latest whales lists on the app."""
        if hasattr(self.app, "whales_full_cache"):
            self.app.whales_full_cache = {
                "whales_btc": self.whales_btc,
                "whales_eth": self.whales_eth,
                "whales_sol": self.whales_sol,
            }
