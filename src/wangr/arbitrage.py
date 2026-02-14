"""Arbitrage screen with live opportunities table."""

from __future__ import annotations

import logging
from typing import Any, Optional

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Label, Static
from textual.worker import Worker

from wangr.api import get_json
from wangr.config import API_TIMEOUT, ARBITRAGE_API_URL, FETCH_INTERVAL
from wangr.sort_modal import SortModal
from wangr.tab_highlight import update_active_tab
from wangr.table_screen import TableNavigationMixin
from wangr.utils import safe_float

logger = logging.getLogger(__name__)


class ArbitrageScreen(TableNavigationMixin, Screen):
    """Screen displaying arbitrage opportunities."""

    BINDINGS = [
        ("b", "go_back", "Go Back"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("up", "cursor_up", "Up"),
        ("left,h", "prev_market", "Prev Market"),
        ("right,l", "next_market", "Next Market"),
        ("ctrl+d", "page_down", "Page Down"),
        ("ctrl+u", "page_up", "Page Up"),
        ("G", "cursor_bottom", "Bottom"),
        ("s", "sort_by_column", "Sort Column"),
        ("S", "toggle_sort_direction", "Toggle Sort"),
        ("f", "toggle_market", "Toggle Market"),
    ]

    MARKET_TYPES = ["futures", "spot", "dex"]
    TABLE_SELECTOR = "#arb-table"

    COLUMN_DEFS_BASE = [
        ("symbol", "Symbol"),
        ("buy_exchange", "Buy"),
        ("sell_exchange", "Sell"),
        ("gross_spread_pct", "Gross"),
        ("net_spread_pct", "Net"),
    ]

    COLUMN_DEFS_FUTURES = [
        ("funding_rate_diff", "Funding Δ"),
        ("net_after_funding_pct", "Net + Fund"),
    ]

    COLUMN_DEFS_TAIL = [
        ("buy_price", "Buy Price"),
        ("sell_price", "Sell Price"),
        ("status", "Status"),
    ]

    market_type: reactive[str] = reactive("futures")

    def __init__(self, data: dict | None = None, cache: dict | None = None) -> None:
        super().__init__()
        self.data = data or {}
        self.cache = cache or {}
        self.opportunities: list[dict] = []
        self.health: dict | None = None
        self.error_message = ""

        self.sort_column: str | None = "net_spread_pct"
        self.sort_reverse: bool = True

        self.update_timer = None
        self._arb_worker: Optional[Worker] = None
        self._fetch_token = 0

        cached = self.cache.get(self.market_type)
        if isinstance(cached, dict):
            if self.market_type == "dex" and not cached.get("opportunities") and cached.get("pairs"):
                self.opportunities = self._normalize_dex_pairs(
                    cached.get("pairs", []) or [],
                    cached.get("base_token"),
                )
                self.health = None
            else:
                self.opportunities = cached.get("opportunities", []) or []
                self.health = cached.get("health")

    def compose(self) -> ComposeResult:
        yield Footer()
        yield Container(
            Container(
                Horizontal(
                    Static("FUTURES", id="arb-market-futures", classes="coin-toggle coin-toggle-active"),
                    Static("SPOT", id="arb-market-spot", classes="coin-toggle"),
                    Static("DEX", id="arb-market-dex", classes="coin-toggle"),
                    id="arb-toggle-row",
                ),
                Label("Arbitrage", id="arb-title", classes="arb-title"),
                Label("", id="arb-line-1", classes="arb-summary"),
                Label("", id="arb-line-2", classes="arb-summary"),
                Label("", id="arb-line-3", classes="arb-summary"),
                Label("", id="arb-status", classes="arb-status"),
                id="arb-summary",
            ),
            DataTable(id="arb-table", zebra_stripes=True, cursor_type="row"),
            id="arb-wrapper",
        )

    async def on_mount(self) -> None:
        for selector in ("#arb-market-futures", "#arb-market-spot", "#arb-market-dex"):
            try:
                self.query_one(selector).can_focus = False
            except Exception:
                pass
        self._update_display()
        self.query_one("#arb-table", DataTable).focus()
        self._fetch_data()
        self.update_timer = self.set_interval(FETCH_INTERVAL, self._fetch_data)

    def on_unmount(self) -> None:
        if self.update_timer:
            self.update_timer.stop()
            self.update_timer = None
        if self._arb_worker and self._arb_worker.is_running:
            self._arb_worker.cancel()
        self._clear_pending_g()

    def on_click(self, event: events.Click) -> None:
        target = event.widget
        if not isinstance(target, Static):
            return
        if target.id == "arb-market-futures":
            self.market_type = "futures"
        elif target.id == "arb-market-spot":
            self.market_type = "spot"
        elif target.id == "arb-market-dex":
            self.market_type = "dex"

    def watch_market_type(self, _old: str, _new: str) -> None:
        if not self.is_mounted:
            return
        self._update_toggle_classes()
        # Clear current data to avoid showing stale rows during switch
        self.opportunities = []
        self.health = None
        self.error_message = ""
        cached = self.cache.get(self.market_type)
        if isinstance(cached, dict):
            if self.market_type == "dex" and not cached.get("opportunities") and cached.get("pairs"):
                self.opportunities = self._normalize_dex_pairs(
                    cached.get("pairs", []) or [],
                    cached.get("base_token"),
                )
                self.health = None
            else:
                self.opportunities = cached.get("opportunities", []) or []
                self.health = cached.get("health")
            self._update_display()
        else:
            self._update_display()
        self._fetch_data()


    def action_toggle_market(self) -> None:
        idx = (self.MARKET_TYPES.index(self.market_type) + 1) % len(self.MARKET_TYPES)
        self.market_type = self.MARKET_TYPES[idx]

    def action_prev_market(self) -> None:
        idx = (self.MARKET_TYPES.index(self.market_type) - 1) % len(self.MARKET_TYPES)
        self.market_type = self.MARKET_TYPES[idx]

    def action_next_market(self) -> None:
        idx = (self.MARKET_TYPES.index(self.market_type) + 1) % len(self.MARKET_TYPES)
        self.market_type = self.MARKET_TYPES[idx]


    def action_sort_by_column(self) -> None:
        self.app.push_screen(
            SortModal(self._column_defs(), self.sort_column, self.sort_reverse),
            self._on_sort_selected,
        )

    def _on_sort_selected(self, result: dict | None) -> None:
        """Handle sort modal result."""
        if result is None:
            return
        self.sort_column = result.get("key")
        self.sort_reverse = result.get("reverse", True)
        self._update_table()

    def action_toggle_sort_direction(self) -> None:
        if self.sort_column is None:
            self.sort_column = self._column_defs()[0][0]
        self.sort_reverse = not self.sort_reverse
        self._update_table()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    # Table navigation inherited from TableNavigationMixin.

    def _column_defs(self) -> list[tuple[str, str]]:
        cols = list(self.COLUMN_DEFS_BASE)
        if self.market_type == "futures":
            cols += self.COLUMN_DEFS_FUTURES
            cols += self.COLUMN_DEFS_TAIL
            return cols
        if self.market_type == "dex":
            return [
                ("symbol", "Pair"),
                ("buy_exchange", "Buy"),
                ("sell_exchange", "Sell"),
                ("gross_spread_pct", "Spread %"),
                ("net_spread_pct", "Net %"),
                ("spread_value", "Δ (USD)"),
                ("buy_price", "Buy Price"),
                ("sell_price", "Sell Price"),
                ("status", "Status"),
            ]
        cols += self.COLUMN_DEFS_TAIL
        return cols

    def _fetch_data(self) -> None:
        if self._arb_worker and self._arb_worker.is_running:
            # Cancel in-flight request so we don't show stale market data
            self._arb_worker.cancel()
        self._fetch_token += 1
        token = self._fetch_token
        market = self.market_type
        self._arb_worker = self.run_worker(
            lambda: self._fetch_arb_data(market, token),
            thread=True,
            name=f"arb_{market}_{token}",
        )

    def _fetch_arb_data(self, market: str, token: int) -> dict[str, Any]:
        prefix = "/futures" if market == "futures" else ""
        try:
            if market == "dex":
                payload, err = get_json(f"{ARBITRAGE_API_URL}/dex/arbitrage", timeout=API_TIMEOUT)
                if err or not isinstance(payload, dict):
                    return {
                        "market": "dex",
                        "token": token,
                        "error": err or "Failed to fetch DEX arbitrage data",
                        "opportunities": [],
                        "health": None,
                    }
                opportunities = self._normalize_dex_pairs(payload.get("pairs", []) or [], payload.get("base_token"))
                return {
                    "market": "dex",
                    "token": token,
                    "opportunities": opportunities,
                    "health": None,
                    "error": None,
                }
            health, err_health = get_json(f"{ARBITRAGE_API_URL}{prefix}/health", timeout=API_TIMEOUT)
            top, err_top = get_json(
                f"{ARBITRAGE_API_URL}{prefix}/arbitrage/top",
                params={"limit": 50, "min_net_pct": -999},
                timeout=API_TIMEOUT,
            )
            if err_health or err_top or not isinstance(top, list):
                return {
                    "market": market,
                    "token": token,
                    "error": err_health or err_top or "Failed to fetch arbitrage data",
                    "opportunities": [],
                    "health": None,
                }
            return {
                "market": market,
                "token": token,
                "opportunities": top,
                "health": health if isinstance(health, dict) else None,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("Arbitrage fetch failed: %s", exc)
            return {"market": market, "token": token, "error": str(exc), "opportunities": [], "health": None}

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state.name != "SUCCESS" or event.worker != self._arb_worker:
            return
        payload = event.worker.result or {}
        market = payload.get("market", self.market_type)
        self.opportunities = payload.get("opportunities", []) or []
        self.health = payload.get("health")
        self.error_message = payload.get("error") or ""
        self.cache[market] = {
            "opportunities": self.opportunities,
            "health": self.health,
        }
        # Only update UI if this result matches the active market
        if market == self.market_type:
            self._update_display()

    def _update_display(self) -> None:
        self._update_toggle_classes()
        self._update_summary()
        self._update_table()

    def _update_toggle_classes(self) -> None:
        update_active_tab(
            self,
            {
                "futures": "#arb-market-futures",
                "spot": "#arb-market-spot",
                "dex": "#arb-market-dex",
            },
            self.market_type,
            active_class="coin-toggle-active",
        )

    def _update_summary(self) -> None:
        rows = self.opportunities
        total = len(rows)
        positive = len([r for r in rows if safe_float(r.get("net_spread_pct"), 0) > 0])
        best_gross = max([safe_float(r.get("gross_spread_pct"), 0) for r in rows], default=0)
        best_net = max([safe_float(r.get("net_spread_pct"), 0) for r in rows], default=0)

        exchanges = set()
        for r in rows:
            exchanges.add(r.get("buy_exchange"))
            exchanges.add(r.get("sell_exchange"))
        exchange_count = len(exchanges)

        top = None
        for row in rows:
            if top is None or safe_float(row.get("net_spread_pct"), 0) > safe_float(top.get("net_spread_pct"), 0):
                top = row

        line1 = f"Total Opportunities {total}  •  Positive Spreads {positive}  •  Exchanges {exchange_count}"
        self.query_one("#arb-line-1", Label).update(line1)

        if top:
            top_symbol = top.get("symbol", "")
            top_net = safe_float(top.get("net_spread_pct"), 0)
            top_text = f"Top Symbol {top_symbol}  Net {top_net:+.3f}%"
        else:
            top_text = "Top Symbol N/A  Net N/A"

        line2 = f"Best Gross {best_gross:+.3f}%  •  Best Net {best_net:+.3f}%  •  {top_text}"
        self.query_one("#arb-line-2", Label).update(line2)

        # Top exchange pair
        pair_best = None
        pair_map: dict[str, dict] = {}
        for row in rows:
            key = f"{row.get('buy_exchange')}→{row.get('sell_exchange')}"
            if key not in pair_map or safe_float(row.get("net_spread_pct"), 0) > safe_float(pair_map[key].get("net_spread_pct"), 0):
                pair_map[key] = row
        for row in pair_map.values():
            if pair_best is None or safe_float(row.get("net_spread_pct"), 0) > safe_float(pair_best.get("net_spread_pct"), 0):
                pair_best = row
        if pair_best:
            pair_label = f"{pair_best.get('buy_exchange')}→{pair_best.get('sell_exchange')}"
            pair_net = safe_float(pair_best.get("net_spread_pct"), 0)
            pair_text = f"Top Pair {pair_label} {pair_net:+.3f}%"
        else:
            pair_text = "Top Pair N/A"

        exchanges_line = ""
        if isinstance(self.health, dict):
            ex = self.health.get("exchanges") or {}
            if isinstance(ex, dict) and ex:
                parts = [f"{k}: {v}" for k, v in list(ex.items())[:5]]
                exchanges_line = "Exchanges " + "  ".join(parts)
        elif rows:
            counts: dict[str, int] = {}
            for row in rows:
                buy = row.get("buy_exchange")
                sell = row.get("sell_exchange")
                if buy:
                    counts[buy] = counts.get(buy, 0) + 1
                if sell:
                    counts[sell] = counts.get(sell, 0) + 1
            parts = [f"{k}: {v}" for k, v in list(counts.items())[:5]]
            exchanges_line = "Exchanges " + "  ".join(parts)
        line3 = f"{pair_text}  •  {exchanges_line}".strip()
        self.query_one("#arb-line-3", Label).update(line3)

        status = f"[red]Error:[/red] {self.error_message}" if self.error_message else ""
        self.query_one("#arb-status", Label).update(status)

    def _sorted_rows(self) -> list[dict]:
        rows = list(self.opportunities)
        if not self.sort_column:
            return rows
        key = self.sort_column
        reverse = self.sort_reverse

        def sort_key(row: dict) -> Any:
            val = row.get(key)
            if isinstance(val, str):
                return val.lower()
            return safe_float(val, 0)

        return sorted(rows, key=sort_key, reverse=reverse)

    def _fmt_pct(self, value: Any) -> str:
        val = safe_float(value, 0)
        sign = "+" if val >= 0 else ""
        return f"{sign}{val:.3f}%"

    def _fmt_price(self, value: Any) -> str:
        val = safe_float(value, 0)
        return f"${val:,.2f}"

    def _spread_color(self, value: Any) -> str:
        return "#2dd4bf" if safe_float(value, 0) >= 0 else "#f87171"

    def _update_table(self) -> None:
        table = self.query_one("#arb-table", DataTable)
        table.clear(columns=True)
        for _key, label in self._column_defs():
            table.add_column(label)

        rows = self._sorted_rows()
        if not rows:
            table.add_row("No opportunities")
            return

        for row in rows:
            gross = row.get("gross_spread_pct")
            net = row.get("net_spread_pct")
            gross_str = f"[{self._spread_color(gross)}]{self._fmt_pct(gross)}[/{self._spread_color(gross)}]"
            net_str = f"[{self._spread_color(net)}]{self._fmt_pct(net)}[/{self._spread_color(net)}]"

            cells = [
                str(row.get("symbol", "")),
                str(row.get("buy_exchange", "")),
                str(row.get("sell_exchange", "")),
                gross_str,
                net_str,
            ]
            if self.market_type == "futures":
                fund = row.get("funding_rate_diff")
                net_fund = row.get("net_after_funding_pct")
                fund_str = f"[{self._spread_color(fund)}]{self._fmt_pct(fund)}[/{self._spread_color(fund)}]"
                net_fund_str = f"[{self._spread_color(net_fund)}]{self._fmt_pct(net_fund)}[/{self._spread_color(net_fund)}]"
                cells.extend([fund_str, net_fund_str])
            if self.market_type == "dex":
                cells.extend(
                    [
                        self._fmt_price(row.get("spread_value")),
                        self._fmt_price(row.get("buy_price")),
                        self._fmt_price(row.get("sell_price")),
                        "Profitable" if safe_float(net, 0) > 0 else "Not Profitable",
                    ]
                )
            else:
                cells.extend(
                    [
                        self._fmt_price(row.get("buy_price")),
                        self._fmt_price(row.get("sell_price")),
                        "Profitable" if safe_float(net, 0) > 0 else "Not Profitable",
                    ]
                )
            table.add_row(*cells)

    @staticmethod
    def _normalize_dex_pairs(pairs: list[dict], base_token: str | None) -> list[dict]:
        rows: list[dict] = []
        for pair in pairs:
            price_entries = [
                (k.replace("_price", "").replace("_", " ").title(), v)
                for k, v in pair.items()
                if isinstance(k, str) and k.endswith("_price") and isinstance(v, (int, float))
            ]
            buy_exchange = "Unknown"
            sell_exchange = "Unknown"
            buy_price = float("inf")
            sell_price = float("-inf")
            for dex, price in price_entries:
                if price < buy_price:
                    buy_price = price
                    buy_exchange = dex
                if price > sell_price:
                    sell_price = price
                    sell_exchange = dex
            if not isinstance(buy_price, (int, float)) or buy_price == float("inf"):
                buy_price = 0.0
            if not isinstance(sell_price, (int, float)) or sell_price == float("-inf"):
                sell_price = 0.0
            spread_pct = safe_float(pair.get("spread_pct"), 0)
            spread_val = safe_float(pair.get("spread"), 0)
            arbitrage = bool(pair.get("arbitrage"))
            symbol = pair.get("token")
            if base_token:
                symbol = f"{symbol}/{base_token}"
            rows.append(
                {
                    "symbol": symbol,
                    "buy_exchange": buy_exchange,
                    "sell_exchange": sell_exchange,
                    "gross_spread_pct": spread_pct,
                    "net_spread_pct": spread_pct if arbitrage else -spread_pct,
                    "spread_value": spread_val,
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "status": "Profitable" if arbitrage else "Not Profitable",
                }
            )
        return rows
