"""WOI full screen with summary header and sortable DataTable."""

import logging
from datetime import datetime
from functools import partial
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, Static
from textual.worker import Worker

from wangr.config import (
    API_TIMEOUT,
    FETCH_INTERVAL,
    FRONTPAGE_API_URL,
    MILLION,
    THOUSAND,
    WOI_TRACKED_USERS_API_URL,
)
from wangr.api import get_json
from wangr.table_screen import SortableTableMixin
from wangr.sparkline import mini_bar
from wangr.utils import format_time, safe_division, safe_float

logger = logging.getLogger(__name__)


class WOIFullScreen(SortableTableMixin, Screen):
    """Screen displaying Wallets of Interest with summary header and sortable table."""

    BINDINGS = [
        ("b", "go_back", "Go Back"),
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
        ("heat", "Heat"),
        ("total_positions", "Trades"),
        ("winning_positions", "Wins"),
        ("win_rate", "Win %"),
        ("total_realized_pnl", "PnL"),
        ("pnl_per_trade", "PnL/Trade"),
        ("long_count", "Longs"),
        ("short_count", "Shorts"),
        ("avg_hold_minutes", "Avg Hold"),
        ("first_open_time", "First Open"),
        ("last_close_time", "Last Close"),
        ("symbols_count", "Symbols"),
    ]
    SORT_COLUMNS = COLUMN_DEFS
    TABLE_SELECTOR = "#woi-table"

    def __init__(self, data: dict, cache: dict | None = None) -> None:
        """Initialize WOI full screen with data."""
        super().__init__()
        self.data = data
        # Aggregates from frontpage API
        self.aggregates = data.get("woi", {}).get("aggregates", {})
        self.top_by_wr = data.get("woi", {}).get("top_3_by_win_rate", [])
        self.top_by_pnl = data.get("woi", {}).get("top_3_by_pnl", [])
        # Users from tracked API
        self.users = []
        if cache and cache.get("users"):
            self.users = cache.get("users", [])
        # Sort state
        self.sort_column = "heat"
        self.sort_reverse = True
        # Timers and workers
        self.update_timer = None
        self._users_worker: Optional[Worker] = None
        self._agg_worker: Optional[Worker] = None

    def _calc_heat(self, user: dict) -> float:
        """Calculate heat score: (wins × win_rate × pnl) / 1000."""
        wins = user.get("winning_positions", 0)
        win_rate = safe_float(user.get("win_rate"), 0)
        pnl = safe_float(user.get("total_realized_pnl"), 0)
        # Normalize PnL to thousands for reasonable numbers
        pnl_k = safe_division(pnl, THOUSAND)
        if pnl_k <= 0:
            return 0
        return (wins * win_rate * pnl_k) / 1000

    def _calc_pnl_per_trade(self, user: dict) -> float:
        """Calculate PnL per trade."""
        pnl = safe_float(user.get("total_realized_pnl"), 0)
        trades = user.get("total_positions", 0)
        if trades == 0:
            return 0
        return safe_division(pnl, trades)

    def _format_ts(self, ts_ms: float) -> str:
        """Format epoch milliseconds to YYYY-MM-DD."""
        if not ts_ms:
            return "N/A"
        try:
            return datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
        except (ValueError, OSError):
            return "N/A"

    def _stacked_bar(self, label: str, value: float, max_val: float, value_str: str, width: int = 30) -> str:
        """Create a stacked bar line."""
        bar = mini_bar(value, max_val, width=width)
        return f"  {label:<6} {bar}  {value_str}"

    def compose(self) -> ComposeResult:
        """Compose the screen UI."""
        yield Header()
        yield Footer()
        # Summary section - two columns
        yield Container(
            Label("", id="woi-title", classes="woi-title"),
            Horizontal(
                # Left column: POSITIONS, WIN/LOSS, HOLD TIME
                Container(
                    Label("POSITIONS", classes="woi-section-header"),
                    Label("", id="woi-pos-long", classes="woi-bar-stacked"),
                    Label("", id="woi-pos-short", classes="woi-bar-stacked"),
                    Label("WIN / LOSS", classes="woi-section-header"),
                    Label("", id="woi-wins", classes="woi-bar-stacked"),
                    Label("", id="woi-losses", classes="woi-bar-stacked"),
                    Label("HOLD TIME", classes="woi-section-header"),
                    Label("", id="woi-hold-stats"),
                    id="woi-left-col",
                ),
                # Right column: LEADERBOARD
                Container(
                    Label("", id="woi-leaderboard", classes="woi-leaderboard"),
                    id="woi-right-col",
                ),
                id="woi-columns",
            ),
            id="woi-summary",
        )
        yield DataTable(id="woi-table", zebra_stripes=True, cursor_type="row")

    def _fetch_users(self) -> list:
        """Fetch users from tracked API."""
        data, err = get_json(WOI_TRACKED_USERS_API_URL, timeout=API_TIMEOUT)
        if err or not isinstance(data, dict):
            logger.error("Error fetching WOI users: %s", err)
            return []
        return data.get("users", [])

    def _fetch_aggregates(self) -> dict:
        """Fetch aggregates from frontpage API."""
        data, err = get_json(FRONTPAGE_API_URL, timeout=API_TIMEOUT)
        if err or not isinstance(data, dict):
            logger.error("Error fetching WOI aggregates: %s", err)
            return {}
        return data.get("woi", {})

    async def on_mount(self) -> None:
        """Mount handler - start data fetching."""
        self._update_summary_display()
        self._update_table_display()
        self.query_one("#woi-table", DataTable).focus()

        self._fetch_all_data()
        self.update_timer = self.set_interval(FETCH_INTERVAL, self._fetch_all_data)

    def on_unmount(self) -> None:
        """Unmount handler - cleanup resources."""
        if self.update_timer:
            self.update_timer.stop()
            self.update_timer = None
        self._clear_pending_g()
        if self._users_worker and self._users_worker.is_running:
            self._users_worker.cancel()
        if self._agg_worker and self._agg_worker.is_running:
            self._agg_worker.cancel()
        self._update_cache()

    def _fetch_all_data(self) -> None:
        """Fetch users and aggregates in parallel."""
        if not (self._users_worker and self._users_worker.is_running):
            self._users_worker = self.run_worker(
                self._fetch_users,
                name="users",
                thread=True,
            )
        if not (self._agg_worker and self._agg_worker.is_running):
            self._agg_worker = self.run_worker(
                self._fetch_aggregates,
                name="aggregates",
                thread=True,
            )

    def on_worker_state_changed(self, event) -> None:
        """Handle worker completion."""
        if event.state.name == "SUCCESS":
            if event.worker.name == "users":
                self.users = event.worker.result
                self._update_table_display()
                self._update_cache()
            elif event.worker.name == "aggregates":
                woi_data = event.worker.result
                self.aggregates = woi_data.get("aggregates", {})
                self.top_by_wr = woi_data.get("top_3_by_win_rate", [])
                self.top_by_pnl = woi_data.get("top_3_by_pnl", [])
                self._update_summary_display()

    def _get_most_active(self) -> list:
        """Get top 3 most active winners (10+ trades, >60% WR), sorted by wins."""
        qualified = [
            u for u in self.users
            if u.get("total_positions", 0) >= 10
            and safe_float(u.get("win_rate"), 0) >= 60
        ]
        return sorted(qualified, key=lambda x: x.get("winning_positions", 0), reverse=True)[:3]

    def _get_best_efficiency(self) -> list:
        """Get top 3 by PnL per trade (10+ trades)."""
        qualified = [
            u for u in self.users
            if u.get("total_positions", 0) >= 10
        ]
        return sorted(qualified, key=lambda x: self._calc_pnl_per_trade(x), reverse=True)[:3]

    def _update_summary_display(self) -> None:
        """Update the summary stats display."""
        agg = self.aggregates

        # Title
        total_pnl = safe_division(agg.get('total_realized_pnl', 0), MILLION)
        total_trades = agg.get('total_trades', 0)
        self.query_one("#woi-title", Label).update(
            f"🔍 Wallets of Interest • ${total_pnl:.1f}M PnL • {total_trades} trades"
        )

        # Positions bars
        long_count = agg.get('long_count', 0)
        short_count = agg.get('short_count', 0)
        pos_max = max(long_count, short_count, 1)
        self.query_one("#woi-pos-long", Label).update(
            self._stacked_bar("Long", long_count, pos_max, str(long_count))
        )
        self.query_one("#woi-pos-short", Label).update(
            self._stacked_bar("Short", short_count, pos_max, str(short_count))
        )

        # Win/Loss bars
        win_share = agg.get('win_share', 0)
        loss_share = 100 - win_share
        self.query_one("#woi-wins", Label).update(
            self._stacked_bar("Wins", win_share, 100, f"{win_share:.0f}%")
        )
        self.query_one("#woi-losses", Label).update(
            self._stacked_bar("Losses", loss_share, 100, f"{loss_share:.0f}%")
        )

        # Hold time stats
        avg_hold = format_time(agg.get('average_hold_minutes', 0))
        min_hold = format_time(agg.get('min_hold_minutes', 0))
        max_hold = format_time(agg.get('max_hold_minutes', 0))
        avg_pnl_k = safe_division(agg.get('average_pnl', 0), THOUSAND)
        self.query_one("#woi-hold-stats", Label).update(
            f"  Avg: {avg_hold}  Min: {min_hold}  Max: {max_hold}\n"
            f"  Avg PnL: ${avg_pnl_k:.1f}k"
        )

        # Leaderboard
        self._update_leaderboard()

    def _update_leaderboard(self) -> None:
        """Update the leaderboard section."""
        lines = []

        # Most Active Winners
        most_active = self._get_most_active()
        lines.append("[bold]🔥 Most Active[/bold] (10+ trades, >60% WR)")
        if most_active:
            for u in most_active:
                wallet = u.get("wallet", "")[:8]
                wins = u.get("winning_positions", 0)
                wr = safe_float(u.get("win_rate"), 0)
                pnl_k = safe_division(u.get("total_realized_pnl", 0), THOUSAND)
                lines.append(f"  {wallet}  {wins} wins │ {wr:.0f}% │ ${pnl_k:.0f}k")
        else:
            lines.append("  [dim]No qualified wallets[/dim]")

        lines.append("")

        # Best Efficiency
        best_eff = self._get_best_efficiency()
        lines.append("[bold]💎 Best Efficiency[/bold] (10+ trades)")
        if best_eff:
            for u in best_eff:
                wallet = u.get("wallet", "")[:8]
                pnl_per = safe_division(self._calc_pnl_per_trade(u), THOUSAND)
                wr = safe_float(u.get("win_rate"), 0)
                pnl_k = safe_division(u.get("total_realized_pnl", 0), THOUSAND)
                lines.append(f"  {wallet}  ${pnl_per:.1f}k/trade │ {wr:.0f}% │ ${pnl_k:.0f}k")
        else:
            lines.append("  [dim]No qualified wallets[/dim]")

        self.query_one("#woi-leaderboard", Label).update("\n".join(lines))

    def _sort_users(self, users: list) -> list:
        """Sort users by the selected column."""

        def get_sort_key(user: dict):
            if self.sort_column == "wallet":
                return user.get("wallet", "")
            elif self.sort_column == "heat":
                return self._calc_heat(user)
            elif self.sort_column == "total_positions":
                return user.get("total_positions", 0)
            elif self.sort_column == "winning_positions":
                return user.get("winning_positions", 0)
            elif self.sort_column == "win_rate":
                return safe_float(user.get("win_rate"), 0)
            elif self.sort_column == "total_realized_pnl":
                return safe_float(user.get("total_realized_pnl"), 0)
            elif self.sort_column == "pnl_per_trade":
                return self._calc_pnl_per_trade(user)
            elif self.sort_column == "long_count":
                return user.get("long_count", 0)
            elif self.sort_column == "short_count":
                return user.get("short_count", 0)
            elif self.sort_column == "avg_hold_minutes":
                return safe_float(user.get("avg_hold_minutes"), 0)
            elif self.sort_column == "first_open_time":
                return user.get("first_open_time", 0)
            elif self.sort_column == "last_close_time":
                return user.get("last_close_time", 0)
            elif self.sort_column == "symbols_count":
                return user.get("symbols_count", 0)
            return 0

        return sorted(users, key=get_sort_key, reverse=self.sort_reverse)

    def _update_table_display(self) -> None:
        """Update the table with current WOI data."""
        table = self.query_one("#woi-table", DataTable)
        table.clear(columns=True)

        for key, label in self.COLUMN_DEFS:
            table.add_column(label, key=key)

        if not self.users:
            table.add_row("Loading...", "", "", "", "", "", "", "", "", "", "", "", "")
            return

        users = self._sort_users(self.users)

        # Also update leaderboard when users change
        self._update_leaderboard()

        for user in users:
            wallet = user.get("wallet", "")
            heat = self._calc_heat(user)
            total_positions = user.get("total_positions", 0)
            winning_positions = user.get("winning_positions", 0)
            win_rate = safe_float(user.get("win_rate"), 0)
            pnl_k = safe_division(user.get("total_realized_pnl", 0), THOUSAND)
            pnl_per_trade = safe_division(self._calc_pnl_per_trade(user), THOUSAND)
            long_count = user.get("long_count", 0)
            short_count = user.get("short_count", 0)
            avg_hold = format_time(safe_float(user.get("avg_hold_minutes"), 0))
            first_open = self._format_ts(user.get("first_open_time", 0))
            last_close = self._format_ts(user.get("last_close_time", 0))
            symbols = user.get("symbols_count", 0)

            # Color heat score
            if heat >= 100:
                heat_str = f"[#FFD700]{heat:.0f}[/#FFD700]"  # Gold
            elif heat >= 50:
                heat_str = f"[#90EE90]{heat:.0f}[/#90EE90]"  # Green
            elif heat > 0:
                heat_str = f"{heat:.0f}"
            else:
                heat_str = "[dim]0[/dim]"

            # Color PnL
            if pnl_k > 0:
                pnl_str = f"[#90EE90]${pnl_k:.0f}k[/#90EE90]"
            elif pnl_k < 0:
                pnl_str = f"[#FF6B6B]${pnl_k:.0f}k[/#FF6B6B]"
            else:
                pnl_str = "$0k"

            table.add_row(
                wallet,
                heat_str,
                str(total_positions),
                str(winning_positions),
                f"{win_rate:.0f}%",
                pnl_str,
                f"${pnl_per_trade:.1f}k",
                str(long_count),
                str(short_count),
                avg_hold,
                first_open,
                last_close,
                str(symbols),
            )

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Handle column header clicks for sorting."""
        if self.sort_column == event.column_key.value:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = event.column_key.value
            self.sort_reverse = True
        self._update_table_display()

    def action_go_back(self) -> None:
        """Go back to previous screen."""
        self.app.pop_screen()

    # Table navigation and sorting inherited from SortableTableMixin.

    def _refresh_table(self) -> None:
        self._update_table_display()

    def _update_cache(self) -> None:
        """Cache latest users list on the app."""
        if hasattr(self.app, "woi_full_cache"):
            self.app.woi_full_cache = {"users": self.users}
