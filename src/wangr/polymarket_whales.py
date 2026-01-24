"""Polymarket whales screen modeled after the web UI."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

import requests
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label
from textual.worker import Worker

from wangr.config import (
    API_TIMEOUT,
    FETCH_INTERVAL,
    MILLION,
    THOUSAND,
    POLYMARKET_TRADER_API_URL,
    POLYMARKET_WHALES_API_URL,
)
from wangr.sort_modal import SortModal
from wangr.sparkline import mini_bar
from wangr.utils import format_bar, safe_division, safe_float

logger = logging.getLogger(__name__)


class PolymarketWhalesScreen(Screen):
    """Screen displaying Polymarket whales with filters, sorting, and details."""

    BINDINGS = [
        ("b", "go_back", "Go Back"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("up", "cursor_up", "Up"),
        ("ctrl+d", "page_down", "Page Down"),
        ("ctrl+u", "page_up", "Page Up"),
        ("G", "cursor_bottom", "Bottom"),
        ("s", "sort_by_column", "Sort Column"),
        ("S", "toggle_sort_direction", "Toggle Sort"),
        ("enter", "toggle_details", "Details"),
        ("r", "reset_filters", "Reset Filters"),
        ("f", "cycle_pnl_filter", "PnL Filter"),
    ]

    COLUMN_DEFS = [
        ("wallet", "Wallet"),
        ("portfolio_value", "Portfolio"),
        ("total_pnl", "PnL"),
        ("analyzed_at", "Analyzed"),
        ("qualification", "Tags"),
    ]

    selected_wallet: reactive[str | None] = reactive(None)

    def __init__(self, data: dict | None = None) -> None:
        super().__init__()
        self.data = data or {}
        self._headers = {
            "Accept": "*/*",
            "Origin": "https://wangr.com",
            "Referer": "https://wangr.com/",
            "User-Agent": "Mozilla/5.0 (wangrcli)",
        }
        self.whales: list[dict] = []
        self.count: int = 0
        self.error_message = ""

        self.sort_column: str | None = "total_pnl"
        self.sort_reverse: bool = True

        self.pnl_filter: str = "all"  # all | profitable | loss

        self.expanded_wallets: set[str] = set()
        self.trader_details: dict[str, dict] = {}
        self.loading_details: dict[str, bool] = {}
        self.positions_data: dict[str, list] = {}
        self.loading_positions: dict[str, bool] = {}
        self.positions_expanded: set[str] = set()

        self.update_timer = None
        self._whales_worker: Optional[Worker] = None
        self._details_worker: Optional[Worker] = None
        self._positions_worker: Optional[Worker] = None
        self._pending_g = False
        self._g_timer = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        yield Container(
            Container(
                Label("Polymarket", id="polywhale-title", classes="polywhale-title"),
                Label("", id="polywhale-subtitle", classes="polywhale-summary"),
                Label("", id="polywhale-profit-bar", classes="polywhale-bar"),
                Label("", id="polywhale-total-line", classes="polywhale-summary-strong"),
                Label("", id="polywhale-mean-line", classes="polywhale-summary"),
                Label("", id="polywhale-median-line", classes="polywhale-summary"),
                Label("", id="polywhale-status", classes="polywhale-status"),
                id="polywhale-summary",
            ),
            DataTable(id="polywhale-table", zebra_stripes=True, cursor_type="row"),
            Container(
                Label("", id="polywhale-details-title", classes="polywhale-details-title"),
                Horizontal(
                    Container(
                        Label("", id="polywhale-stat-win-label", classes="polywhale-stat-label"),
                        Label("", id="polywhale-stat-win-value", classes="polywhale-stat-value"),
                        Label("", id="polywhale-stat-win-sub", classes="polywhale-stat-sub"),
                        id="polywhale-stat-win",
                    ),
                    Container(
                        Label("", id="polywhale-stat-open-label", classes="polywhale-stat-label"),
                        Label("", id="polywhale-stat-open-value", classes="polywhale-stat-value"),
                        Label("", id="polywhale-stat-open-sub", classes="polywhale-stat-sub"),
                        id="polywhale-stat-open",
                    ),
                    Container(
                        Label("", id="polywhale-stat-closed-label", classes="polywhale-stat-label"),
                        Label("", id="polywhale-stat-closed-value", classes="polywhale-stat-value"),
                        Label("", id="polywhale-stat-closed-sub", classes="polywhale-stat-sub"),
                        id="polywhale-stat-closed",
                    ),
                    Container(
                        Label("", id="polywhale-stat-volume-label", classes="polywhale-stat-label"),
                        Label("", id="polywhale-stat-volume-value", classes="polywhale-stat-value"),
                        Label("", id="polywhale-stat-volume-sub", classes="polywhale-stat-sub"),
                        id="polywhale-stat-volume",
                    ),
                    id="polywhale-stat-grid",
                ),
                Label("Top Open Positions", classes="polywhale-section-header"),
                DataTable(id="polywhale-open", zebra_stripes=True, cursor_type="row", classes="polywhale-open-table"),
                Label("Top Closed Positions", classes="polywhale-section-header"),
                DataTable(id="polywhale-closed", zebra_stripes=True, cursor_type="row", classes="polywhale-closed-table"),
                DataTable(id="polywhale-positions", zebra_stripes=True, cursor_type="row", classes="polywhale-positions-table"),
                id="polywhale-details",
                classes="polywhale-details-card",
            ),
            id="polywhale-wrapper",
        )

    async def on_mount(self) -> None:
        for selector in ("#polywhale-open", "#polywhale-closed", "#polywhale-positions"):
            try:
                self.query_one(selector).can_focus = False
            except Exception:
                pass
        self._update_display()
        self.query_one("#polywhale-table", DataTable).focus()
        self._fetch_whales()
        self.update_timer = self.set_interval(FETCH_INTERVAL, self._fetch_whales)

    def on_unmount(self) -> None:
        if self.update_timer:
            self.update_timer.stop()
            self.update_timer = None
        for worker in (self._whales_worker, self._details_worker, self._positions_worker):
            if worker and worker.is_running:
                worker.cancel()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "polywhale-table":
            return
        wallet = self._row_key_to_wallet(event.row_key)
        if wallet:
            self.selected_wallet = str(wallet)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "polywhale-table":
            return
        wallet = self._row_key_to_wallet(event.row_key)
        if wallet:
            self.selected_wallet = str(wallet)

    def on_key(self, event: events.Key) -> None:
        focused = self.focused
        if not isinstance(focused, DataTable) or focused.id != "polywhale-table":
            return
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
        elif event.key == "enter":
            event.stop()
            self.action_toggle_details()
        else:
            self._clear_pending_g()

    def action_cursor_down(self) -> None:
        self.query_one("#polywhale-table", DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#polywhale-table", DataTable).action_cursor_up()

    def action_page_down(self) -> None:
        self.query_one("#polywhale-table", DataTable).action_page_down()

    def action_page_up(self) -> None:
        self.query_one("#polywhale-table", DataTable).action_page_up()

    def action_cursor_top(self) -> None:
        table = self.query_one("#polywhale-table", DataTable)
        if table.row_count > 0:
            table.move_cursor(row=0)

    def action_cursor_bottom(self) -> None:
        table = self.query_one("#polywhale-table", DataTable)
        if table.row_count > 0:
            table.move_cursor(row=table.row_count - 1)

    def action_go_back(self) -> None:
        self.app.pop_screen()

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
        self._update_table_display()

    def action_toggle_details(self) -> None:
        wallet = self.selected_wallet or self._current_wallet_from_table()
        if not wallet:
            return
        if wallet in self.expanded_wallets:
            self.expanded_wallets.remove(wallet)
        else:
            self.expanded_wallets.add(wallet)
            self._fetch_details(wallet)
        self._update_details_display()

    def action_toggle_positions(self) -> None:
        wallet = self.selected_wallet or self._current_wallet_from_table()
        if not wallet:
            return
        if wallet in self.positions_expanded:
            self.positions_expanded.remove(wallet)
        else:
            self.positions_expanded.add(wallet)
            self._fetch_positions(wallet)
        self._update_positions_table()

    def action_reset_filters(self) -> None:
        self.pnl_filter = "all"
        self._update_table_display()

    def action_cycle_pnl_filter(self) -> None:
        order = ["all", "profitable", "loss"]
        idx = (order.index(self.pnl_filter) + 1) % len(order)
        self.pnl_filter = order[idx]
        self._update_table_display()

    def _fetch_whales(self) -> None:
        if self._whales_worker and self._whales_worker.is_running:
            return
        self._whales_worker = self.run_worker(self._fetch_whales_data, thread=True, name="polywhales")

    def _fetch_whales_data(self) -> dict[str, Any]:
        try:
            resp = requests.get(POLYMARKET_WHALES_API_URL, headers=self._headers, timeout=API_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            return {
                "whales": data.get("whales", []) or [],
                "count": data.get("count") or 0,
                "error": None,
            }
        except requests.RequestException as exc:
            logger.error("Failed to fetch whales: %s", exc)
            return {"whales": [], "count": 0, "error": str(exc)}
        except ValueError as exc:
            logger.error("Failed to parse whales JSON: %s", exc)
            return {"whales": [], "count": 0, "error": str(exc)}

    def _fetch_details(self, wallet: str) -> None:
        if self.loading_details.get(wallet):
            return
        self.loading_details[wallet] = True
        self._details_worker = self.run_worker(
            lambda: self._fetch_trader_details(wallet),
            thread=True,
            name=f"details_{wallet}",
        )

    def _fetch_trader_details(self, wallet: str) -> dict[str, Any]:
        try:
            resp = requests.get(
                f"{POLYMARKET_TRADER_API_URL}/{wallet}",
                headers=self._headers,
                timeout=API_TIMEOUT,
            )
            resp.raise_for_status()
            return {"wallet": wallet, "payload": resp.json()}
        except requests.RequestException as exc:
            logger.error("Failed to fetch trader details: %s", exc)
            return {"error": str(exc), "wallet": wallet}
        except ValueError as exc:
            logger.error("Failed to parse trader details JSON: %s", exc)
            return {"error": str(exc), "wallet": wallet}

    def _fetch_positions(self, wallet: str) -> None:
        if self.loading_positions.get(wallet):
            return
        self.loading_positions[wallet] = True
        self._positions_worker = self.run_worker(
            lambda: self._fetch_positions_data(wallet),
            thread=True,
            name=f"positions_{wallet}",
        )

    def _fetch_positions_data(self, wallet: str) -> dict[str, Any]:
        try:
            resp = requests.get(
                f"{POLYMARKET_TRADER_API_URL}/{wallet}",
                params={"include_positions": "true"},
                headers=self._headers,
                timeout=API_TIMEOUT,
            )
            resp.raise_for_status()
            return {"wallet": wallet, "positions": resp.json().get("all_positions", [])}
        except requests.RequestException as exc:
            logger.error("Failed to fetch positions: %s", exc)
            return {"wallet": wallet, "positions": [], "error": str(exc)}
        except ValueError as exc:
            logger.error("Failed to parse positions JSON: %s", exc)
            return {"wallet": wallet, "positions": [], "error": str(exc)}

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state.name != "SUCCESS":
            return
        if event.worker == self._whales_worker:
            payload = event.worker.result or {}
            self.whales = payload.get("whales", [])
            self.count = payload.get("count", 0)
            self.error_message = payload.get("error") or ""
            self._update_display()
        elif event.worker == self._details_worker:
            result = event.worker.result or {}
            wallet = result.get("wallet")
            if wallet:
                self.loading_details[wallet] = False
                if result.get("error"):
                    self.trader_details[wallet] = {"error": result.get("error")}
                else:
                    self.trader_details[wallet] = result.get("payload", {})
            self._update_details_display()
        elif event.worker == self._positions_worker:
            result = event.worker.result or {}
            wallet = result.get("wallet")
            if wallet:
                self.loading_positions[wallet] = False
                if not result.get("error"):
                    self.positions_data[wallet] = result.get("positions", [])
            self._update_positions_table()

    def _update_display(self) -> None:
        self._update_count_display()
        self._update_table_display()
        self._update_details_display()

    def _update_count_display(self) -> None:
        total = len(self.whales)
        filtered = len(self._filtered_whales())
        poly = self.data.get("polymarket", {})
        traders = poly.get("traders_tracked", 0)
        whales = poly.get("whale_count", 0)
        super_traders = poly.get("super_trader_count", 0)
        total_pnl = safe_division(poly.get("total_pnl", 0), MILLION)
        total_vol = safe_division(poly.get("total_recent_volume", 0), MILLION)
        total_port = safe_division(poly.get("total_portfolio_value", 0), MILLION)
        mean_wr = poly.get("mean_win_rate", 0)
        median_wr = poly.get("median_win_rate", 0)
        count_label = f"{filtered} / {total} whales" if filtered != total else f"{total} whales"
        line1 = f"{count_label}  •  {super_traders} super traders  •  {traders:,} tracked  •  ${total_vol:.1f}M volume"
        self.query_one("#polywhale-subtitle", Label).update(line1)

        profitable = poly.get("profitable_count", 0)
        losing = poly.get("losing_count", 0)
        profit_pct = poly.get("profitable_pct", 0)
        bar = format_bar(
            f"Profitable: {profitable}",
            f"Losing: {losing}",
            profitable,
            losing,
            width=26,
        )
        self.query_one("#polywhale-profit-bar", Label).update(bar)

        pnl_color = "#2dd4bf" if total_pnl >= 0 else "#f87171"
        total_line = f"Total Portfolio ${total_port:.2f}M    Total PnL [{pnl_color}]{total_pnl:+.2f}M[/{pnl_color}]"
        self.query_one("#polywhale-total-line", Label).update(total_line)

        mean_port = safe_division(poly.get("mean_portfolio_value", 0), THOUSAND)
        median_port = safe_division(poly.get("median_portfolio_value", 0), THOUSAND)
        mean_pnl = safe_division(poly.get("mean_pnl", 0), THOUSAND)
        median_pnl = safe_division(poly.get("median_pnl", 0), THOUSAND)
        self.query_one("#polywhale-mean-line", Label).update(
            f"Mean: ${mean_port:.1f}K    Mean PnL: {mean_pnl:+.1f}K    Mean WR: {mean_wr:.1f}%"
        )
        self.query_one("#polywhale-median-line", Label).update(
            f"Median: ${median_port:.1f}K    Median PnL: {median_pnl:+.1f}K    Median WR: {median_wr:.1f}%"
        )
        status = f"[red]Error:[/red] {self.error_message}" if self.error_message else ""
        self.query_one("#polywhale-status", Label).update(status)

    def _filtered_whales(self) -> list[dict]:
        def passes(whale: dict) -> bool:
            pnl = safe_float(whale.get("total_pnl"), 0)
            if self.pnl_filter == "profitable" and pnl <= 0:
                return False
            if self.pnl_filter == "loss" and pnl >= 0:
                return False
            return True

        return [w for w in self.whales if passes(w)]

    def _sorted_whales(self) -> list[dict]:
        whales = list(self._filtered_whales())
        col = self.sort_column
        reverse = self.sort_reverse

        def key_fn(whale: dict) -> Any:
            if col == "wallet":
                return whale.get("wallet", "")
            if col == "analyzed_at":
                return whale.get("analyzed_at", "")
            if col == "qualification":
                return ",".join(whale.get("qualification", []) or [])
            return safe_float(whale.get(col), 0)

        return sorted(whales, key=key_fn, reverse=reverse)

    def _update_table_display(self) -> None:
        table = self.query_one("#polywhale-table", DataTable)
        table.clear(columns=True)
        table.add_column("Wallet")
        table.add_column("Portfolio", width=12)
        table.add_column("PnL", width=12)
        table.add_column("Analyzed", width=12)
        table.add_column("Tags")

        whales = self._sorted_whales()
        if not whales:
            table.add_row("No whales", "", "", "", "")
            return

        for whale in whales:
            wallet = whale.get("wallet", "")
            portfolio = safe_float(whale.get("portfolio_value"), 0)
            pnl = safe_float(whale.get("total_pnl"), 0)
            analyzed = whale.get("analyzed_at", "")
            tags = ", ".join(whale.get("qualification", []) or [])
            analyzed_fmt = self._format_date(analyzed)
            pnl_str = f"{pnl:+,.0f}"
            row = [wallet, f"{portfolio:,.0f}", pnl_str, analyzed_fmt, tags]
            table.add_row(*row, key=wallet)

    def _on_sort_selected(self, result: dict | None) -> None:
        """Apply sort selection from modal."""
        if not result:
            return
        self.sort_column = result.get("key")
        self.sort_reverse = result.get("reverse", self.sort_reverse)
        self._update_table_display()

    def _update_details_display(self) -> None:
        wallet = self.selected_wallet
        if not wallet or wallet not in self.expanded_wallets:
            self.query_one("#polywhale-details", Container).display = False
            return
        self.query_one("#polywhale-details", Container).display = True

        title = f"Details: {wallet}"
        whale = next((w for w in self.whales if w.get("wallet") == wallet), {})
        portfolio = safe_float(whale.get("portfolio_value"), 0)
        pnl = safe_float(whale.get("total_pnl"), 0)
        analyzed = whale.get("analyzed_at", "")
        analyzed_fmt = self._format_date(analyzed)
        pnl_color = "#2dd4bf" if pnl >= 0 else "#f87171"
        title = (
            f"[bold]{wallet[:6]}…{wallet[-4:]}[/bold]  "
            f"[dim]Portfolio[/dim] ${portfolio:,.2f}  "
            f"[{pnl_color}]PnL {pnl:+,.2f}[/{pnl_color}]  "
            f"[dim]{analyzed_fmt}[/dim]"
        )
        self.query_one("#polywhale-details-title", Label).update(title)

        if self.loading_details.get(wallet):
            self._update_stat_grid_error("Loading trader details...")
            self._update_open_closed_tables(None, None)
            return

        payload = self.trader_details.get(wallet, {})
        if payload.get("error"):
            self._update_stat_grid_error(f"Failed to load details: {payload.get('error')}")
            self._update_open_closed_tables([], [])
            return
        details = payload.get("details")
        if not details and any(k in payload for k in ("open_positions", "closed_positions", "recent_volume")):
            details = payload
        if not details:
            self._update_stat_grid_error("Failed to load details.")
            self._update_open_closed_tables([], [])
            return

        closed = details.get("closed_positions", {})
        open_pos = details.get("open_positions", {})

        win_rate = _fmt_pct(closed.get("win_rate"))
        open_pnl = _fmt_usd(open_pos.get("pnl"))
        closed_pnl = _fmt_usd(closed.get("pnl"))
        vol = _fmt_usd(details.get("recent_volume"))

        self.query_one("#polywhale-stat-win-label", Label).update("[dim]WIN RATE[/dim]")
        self.query_one("#polywhale-stat-win-value", Label).update(f"[bold]{win_rate}[/bold]")
        self.query_one("#polywhale-stat-win-sub", Label).update(
            f"[dim]{closed.get('winning', 0)}W - {closed.get('losing', 0)}L[/dim]"
        )

        self.query_one("#polywhale-stat-open-label", Label).update("[dim]OPEN PNL[/dim]")
        self.query_one("#polywhale-stat-open-value", Label).update(
            f"[{_pnl_color(open_pos.get('pnl'))}]{open_pnl}[/{_pnl_color(open_pos.get('pnl'))}]"
        )
        self.query_one("#polywhale-stat-open-sub", Label).update(
            f"[dim]{open_pos.get('count', 0)} Pos[/dim]"
        )

        self.query_one("#polywhale-stat-closed-label", Label).update("[dim]CLOSED PNL[/dim]")
        self.query_one("#polywhale-stat-closed-value", Label).update(
            f"[{_pnl_color(closed.get('pnl'))}]{closed_pnl}[/{_pnl_color(closed.get('pnl'))}]"
        )
        self.query_one("#polywhale-stat-closed-sub", Label).update(
            f"[dim]{closed.get('count', 0)} Pos[/dim]"
        )

        self.query_one("#polywhale-stat-volume-label", Label).update("[dim]VOLUME[/dim]")
        self.query_one("#polywhale-stat-volume-value", Label).update(f"[bold]{vol}[/bold]")
        self.query_one("#polywhale-stat-volume-sub", Label).update(
            f"[dim]{details.get('recent_trades_count', 0)} Trades[/dim]"
        )

        self._update_open_closed_tables(
            details.get("top_open_positions", [])[:5],
            details.get("top_closed_positions", [])[:5],
        )

        self._update_positions_table()

    def _update_stat_grid_error(self, message: str) -> None:
        self.query_one("#polywhale-stat-win-label", Label).update(message)
        self.query_one("#polywhale-stat-win-value", Label).update("")
        self.query_one("#polywhale-stat-win-sub", Label).update("")
        for key in ("open", "closed", "volume"):
            self.query_one(f"#polywhale-stat-{key}-label", Label).update("")
            self.query_one(f"#polywhale-stat-{key}-value", Label).update("")
            self.query_one(f"#polywhale-stat-{key}-sub", Label).update("")

    def _update_open_closed_tables(self, open_positions: list | None, closed_positions: list | None) -> None:
        open_table = self.query_one("#polywhale-open", DataTable)
        closed_table = self.query_one("#polywhale-closed", DataTable)
        open_table.clear(columns=True)
        closed_table.clear(columns=True)

        open_table.add_column("Market")
        open_table.add_column("Size", width=10)
        open_table.add_column("PnL", width=12)
        open_table.add_column("%", width=7)

        closed_table.add_column("Market")
        closed_table.add_column("PnL", width=12)
        closed_table.add_column("%", width=7)

        if not open_positions:
            open_table.add_row("No open positions", "", "", "")
        else:
            for pos in open_positions:
                open_table.add_row(
                    str(pos.get("market", "")),
                    _fmt_usd(pos.get("size")),
                    _fmt_usd(pos.get("pnl")),
                    _fmt_pct(pos.get("percent_pnl")),
                )

        if not closed_positions:
            closed_table.add_row("No closed positions", "", "")
        else:
            for pos in closed_positions:
                closed_table.add_row(
                    str(pos.get("market", "")),
                    _fmt_usd(pos.get("pnl")),
                    _fmt_pct(pos.get("percent_pnl")),
                )

    def _update_positions_table(self) -> None:
        table = self.query_one("#polywhale-positions", DataTable)
        wallet = self.selected_wallet
        if not wallet or wallet not in self.positions_expanded:
            table.display = False
            return
        table.display = True
        table.clear(columns=True)

        positions = self.positions_data.get(wallet)
        if not positions:
            table.add_column("Positions")
            table.add_row("Loading positions..." if self.loading_positions.get(wallet) else "No positions")
            return

        columns = _infer_position_columns(positions)
        for _key, label in columns:
            table.add_column(label)

        for pos in positions[:100]:
            row = [_format_cell(key, pos.get(key)) for key, _label in columns]
            table.add_row(*row)

    def _current_wallet_from_table(self) -> str | None:
        table = self.query_one("#polywhale-table", DataTable)
        try:
            row_idx = table.cursor_row
        except Exception:
            return None
        try:
            return self._row_key_to_wallet(table.row_keys[row_idx])
        except Exception:
            return None

    def _clear_pending_g(self) -> None:
        self._pending_g = False
        if self._g_timer:
            self._g_timer.stop()
            self._g_timer = None

    @staticmethod
    def _row_key_to_wallet(row_key: Any) -> str | None:
        if row_key is None:
            return None
        for attr in ("value", "key"):
            if hasattr(row_key, attr):
                val = getattr(row_key, attr)
                if val:
                    return str(val)
        if isinstance(row_key, str):
            return row_key
        return str(row_key)

    def _short_wallet(self, wallet: str) -> str:
        if not wallet:
            return ""
        if len(wallet) < 10:
            return wallet
        return f"{wallet[:6]}…{wallet[-4:]}"

    def _build_top_by_portfolio(self, items: list[dict]) -> str:
        if not items:
            return "  [dim]No data[/dim]"
        max_port = max(safe_float(i.get("portfolio_value"), 0) for i in items) or 1
        lines = ["Wallet            Portfolio        PnL"]
        for item in items:
            wallet = self._short_wallet(item.get("wallet", ""))
            port = safe_division(item.get("portfolio_value", 0), MILLION)
            pnl = safe_division(item.get("total_pnl", 0), THOUSAND)
            bar = mini_bar(item.get("portfolio_value", 0), max_port, width=8)
            color = "#2dd4bf" if pnl >= 0 else "#f87171"
            lines.append(f"{wallet:<16} {bar} ${port:>5.2f}M  [{color}]{pnl:+.1f}K[/{color}]")
        return "\n".join(lines)

    def _build_top_by_pnl(self, items: list[dict]) -> str:
        if not items:
            return "  [dim]No data[/dim]"
        max_pnl = max(abs(safe_float(i.get("total_pnl"), 0)) for i in items) or 1
        lines = ["Wallet            PnL            Portfolio"]
        for item in items:
            wallet = self._short_wallet(item.get("wallet", ""))
            pnl_m = safe_division(item.get("total_pnl", 0), MILLION)
            port_k = safe_division(item.get("portfolio_value", 0), THOUSAND)
            bar = mini_bar(abs(item.get("total_pnl", 0)), max_pnl, width=8)
            color = "#2dd4bf" if pnl_m >= 0 else "#f87171"
            lines.append(f"{wallet:<16} {bar} [{color}]{pnl_m:+.2f}M[/{color}]  ${port_k:>6.1f}K")
        return "\n".join(lines)

    def _build_top_by_win_rate(self, items: list[dict]) -> str:
        if not items:
            return "  [dim]No data[/dim]"
        lines = ["Wallet            Win Rate       PnL"]
        for item in items:
            wallet = self._short_wallet(item.get("wallet", ""))
            wr = safe_float(item.get("win_rate"), 0)
            pos = item.get("positions_count", 0)
            pnl_k = safe_division(item.get("total_pnl", 0), THOUSAND)
            bar = mini_bar(wr, 100, width=8)
            color = "#2dd4bf" if pnl_k >= 0 else "#f87171"
            lines.append(f"{wallet:<16} {bar} {wr:>5.1f}% ({pos})  [{color}]{pnl_k:+.1f}K[/{color}]")
        return "\n".join(lines)

    @staticmethod
    def _format_date(value: str) -> str:
        if not value:
            return ""
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d")
        except ValueError:
            return value


def _fmt_pct(value: Any) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return str(value)


def _fmt_usd(value: Any) -> str:
    if value is None:
        return "$0"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"${num:,.0f}"


def _pnl_color(value: Any) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "text"
    return "#2dd4bf" if num >= 0 else "#f87171"


def _infer_position_columns(positions: list[dict]) -> list[tuple[str, str]]:
    preferred = [
        ("market", "Market"),
        ("side", "Side"),
        ("size", "Size"),
        ("pnl", "PnL"),
        ("percent_pnl", "%"),
        ("opened_at", "Opened"),
        ("closed_at", "Closed"),
    ]
    if not positions:
        return preferred
    keys = list(positions[0].keys())
    columns = [col for col in preferred if col[0] in keys]
    if not columns:
        columns = [(k, k.replace("_", " ").title()) for k in keys[:6]]
    return columns


def _format_cell(key: str, value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        if "percent" in key or key.endswith("_pct"):
            return f"{value:.2f}%"
        if "pnl" in key or "size" in key:
            return f"{value:,.0f}"
        return f"{value:.2f}"
    return str(value)
