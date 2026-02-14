"""Polymarket full screen with detailed pmarkets data."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Optional

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Label, Static
from textual.worker import Worker

from wangr.api import ApiError, get_json, get_json_or_raise
from wangr.formatters import fmt_num, fmt_pct
from wangr.tab_highlight import update_active_tab
from wangr.config import API_TIMEOUT, FETCH_INTERVAL, PMARKETS_BASE_URL
from wangr.utils import safe_float

logger = logging.getLogger(__name__)


class PolymarketFullScreen(Screen):
    """Screen displaying full Polymarket pmarkets data for BTC/ETH/SOL."""

    BINDINGS = [
        ("b", "go_back", "Go Back"),
        ("left,h", "prev_symbol", "Previous"),
        ("right,l", "next_symbol", "Next"),
        ("[", "prev_window", "Prev Window"),
        ("]", "next_window", "Next Window"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("up", "cursor_up", "Up"),
        ("ctrl+d", "page_down", "Page Down"),
        ("ctrl+u", "page_up", "Page Up"),
        ("G", "cursor_bottom", "Bottom"),
    ]

    SYMBOLS = ["BTC", "ETH", "SOL"]
    WINDOWS = ["30d", "90d", "365d"]
    INTERVALS = ["1h", "4h", "1d"]

    selected_symbol: reactive[str] = reactive("BTC")
    selected_window: reactive[str] = reactive("30d")

    def __init__(self, data: dict | None = None) -> None:
        super().__init__()
        self.data = data or {}
        self.strikes: dict = {}
        self.updown: dict = {}
        self.summary: dict = {}
        self.pivots: dict = {}
        self.distributions: dict[str, Optional[dict]] = {}
        self.mispricings: Optional[dict] = None
        self.regime_analysis: Optional[dict] = None
        self.error_message = ""
        self.update_timer = None
        self._data_worker: Optional[Worker] = None

    def compose(self) -> ComposeResult:
        yield Footer()
        yield Horizontal(
            Static("₿ BTC", id="poly-coin-btc", classes="coin-toggle coin-toggle-active"),
            Static("Ξ ETH", id="poly-coin-eth", classes="coin-toggle"),
            Static("◎ SOL", id="poly-coin-sol", classes="coin-toggle"),
            id="polyfull-coins",
        )
        yield Horizontal(
            Static("30d", id="poly-window-30d", classes="window-toggle window-toggle-active"),
            Static("90d", id="poly-window-90d", classes="window-toggle"),
            Static("365d", id="poly-window-365d", classes="window-toggle"),
            id="polyfull-window",
        )
        yield Container(
            Label("", id="polyfull-title", classes="polyfull-title"),
            Horizontal(
                Container(
                    Label("SENTIMENT", classes="polyfull-section-header"),
                    Label("", id="polyfull-sentiment", classes="polyfull-metric"),
                    Label("PIVOTS", classes="polyfull-section-header"),
                    Label("", id="polyfull-pivots-summary", classes="polyfull-metric"),
                    id="polyfull-left-col",
                ),
                Container(
                    Label("DISTRIBUTIONS", classes="polyfull-section-header"),
                    Label("", id="polyfull-distributions", classes="polyfull-metric"),
                    Label("REGIME", classes="polyfull-section-header"),
                    Label("", id="polyfull-regime", classes="polyfull-metric"),
                    id="polyfull-right-col",
                ),
                id="polyfull-columns",
            ),
            Label("", id="polyfull-status", classes="polyfull-status"),
            id="polyfull-summary",
        )
        yield DataTable(id="polyfull-pivots", zebra_stripes=True, cursor_type="row")
        yield DataTable(id="polyfull-mispricings", zebra_stripes=True, cursor_type="row")
        yield DataTable(id="polyfull-strikes", zebra_stripes=True, cursor_type="row")
        yield DataTable(id="polyfull-updown", zebra_stripes=True, cursor_type="row")

    async def on_mount(self) -> None:
        self._update_toggle_classes()
        self._update_display()
        self.query_one("#polyfull-mispricings", DataTable).focus()
        self._fetch_all_data()
        self.update_timer = self.set_interval(FETCH_INTERVAL, self._fetch_all_data)

    def on_unmount(self) -> None:
        if self.update_timer:
            self.update_timer.stop()
            self.update_timer = None
        if self._data_worker and self._data_worker.is_running:
            self._data_worker.cancel()

    def on_click(self, event: events.Click) -> None:
        target = event.widget
        if not isinstance(target, Static):
            return
        if target.id == "poly-coin-btc":
            self.selected_symbol = "BTC"
        elif target.id == "poly-coin-eth":
            self.selected_symbol = "ETH"
        elif target.id == "poly-coin-sol":
            self.selected_symbol = "SOL"
        elif target.id == "poly-window-30d":
            self.selected_window = "30d"
        elif target.id == "poly-window-90d":
            self.selected_window = "90d"
        elif target.id == "poly-window-365d":
            self.selected_window = "365d"

    def watch_selected_symbol(self, _old: str, _new: str) -> None:
        self._update_toggle_classes()
        self._fetch_all_data()

    def watch_selected_window(self, _old: str, _new: str) -> None:
        self._update_toggle_classes()
        self._fetch_all_data()

    def action_prev_symbol(self) -> None:
        idx = (self.SYMBOLS.index(self.selected_symbol) - 1) % len(self.SYMBOLS)
        self.selected_symbol = self.SYMBOLS[idx]

    def action_next_symbol(self) -> None:
        idx = (self.SYMBOLS.index(self.selected_symbol) + 1) % len(self.SYMBOLS)
        self.selected_symbol = self.SYMBOLS[idx]

    def action_prev_window(self) -> None:
        idx = (self.WINDOWS.index(self.selected_window) - 1) % len(self.WINDOWS)
        self.selected_window = self.WINDOWS[idx]

    def action_next_window(self) -> None:
        idx = (self.WINDOWS.index(self.selected_window) + 1) % len(self.WINDOWS)
        self.selected_window = self.WINDOWS[idx]

    def action_cursor_down(self) -> None:
        self.query_one("#polyfull-mispricings", DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#polyfull-mispricings", DataTable).action_cursor_up()

    def action_page_down(self) -> None:
        self.query_one("#polyfull-mispricings", DataTable).action_page_down()

    def action_page_up(self) -> None:
        self.query_one("#polyfull-mispricings", DataTable).action_page_up()

    def action_cursor_bottom(self) -> None:
        self.query_one("#polyfull-mispricings", DataTable).action_cursor_bottom()

    def _update_toggle_classes(self) -> None:
        update_active_tab(
            self,
            {
                "BTC": "#poly-coin-btc",
                "ETH": "#poly-coin-eth",
                "SOL": "#poly-coin-sol",
            },
            self.selected_symbol,
            active_class="coin-toggle-active",
        )
        update_active_tab(
            self,
            {
                "30d": "#poly-window-30d",
                "90d": "#poly-window-90d",
                "365d": "#poly-window-365d",
            },
            self.selected_window,
            active_class="window-toggle-active",
        )

    def _fetch_all_data(self) -> None:
        if self._data_worker and self._data_worker.is_running:
            return
        self._data_worker = self.run_worker(
            self._fetch_full_data,
            name="pmarkets",
            thread=True,
        )

    def _fetch_full_data(self) -> dict[str, Any]:
        symbol = self.selected_symbol.lower()
        window = self.selected_window

        def get_required(path: str, params: dict | None = None) -> dict:
            url = f"{PMARKETS_BASE_URL}/{path}"
            return get_json_or_raise(url, params=params, timeout=API_TIMEOUT)

        def get_optional(path: str, params: dict | None = None) -> Optional[dict]:
            url = f"{PMARKETS_BASE_URL}/{path}"
            data, err = get_json(url, params=params, timeout=API_TIMEOUT)
            if err or not isinstance(data, dict):
                return None
            return data

        try:
            with ThreadPoolExecutor(max_workers=6) as executor:
                core_futs = {
                    "strikes": executor.submit(get_required, f"{symbol}/strikes/latest"),
                    "updown": executor.submit(get_required, f"{symbol}/updown/latest"),
                    "summary": executor.submit(get_required, f"{symbol}/updown/summary"),
                    "pivots": executor.submit(get_required, f"{symbol}/strikes/pivot"),
                }
                strikes = core_futs["strikes"].result()
                updown = core_futs["updown"].result()
                summary = core_futs["summary"].result()
                pivots = core_futs["pivots"].result()

                current_price = safe_float(strikes.get("price_approx"), 0)

                dist_futs = {
                    interval: executor.submit(
                        get_optional,
                        f"{symbol}/distribution",
                        {"interval": interval, "window": window},
                    )
                    for interval in self.INTERVALS
                }
                distributions = {interval: fut.result() for interval, fut in dist_futs.items()}

                mispricings = None
                if current_price > 0:
                    mispricings = get_optional(
                        f"{symbol}/mispricings",
                        {"current_price": current_price, "window": window},
                    )

                regime_analysis = None
                compare = get_optional(f"{symbol}/distribution-compare", {"interval": "1d"})
                if compare:
                    regime_analysis = compare.get("regime_analysis")
        except ApiError as exc:
            logger.error("Polymarket fetch failed: %s", exc)
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.error("Polymarket fetch failed: %s", exc)
            return {"error": str(exc)}

        return {
            "strikes": strikes,
            "updown": updown,
            "summary": summary,
            "pivots": pivots,
            "distributions": distributions,
            "mispricings": mispricings,
            "regime_analysis": regime_analysis,
        }

    def on_worker_state_changed(self, event) -> None:
        if event.worker != self._data_worker or event.state.name != "SUCCESS":
            return
        payload = event.worker.result or {}
        self.error_message = payload.get("error", "")
        if not self.error_message:
            self.strikes = payload.get("strikes", {})
            self.updown = payload.get("updown", {})
            self.summary = payload.get("summary", {})
            self.pivots = payload.get("pivots", {})
            self.distributions = payload.get("distributions", {})
            self.mispricings = payload.get("mispricings", None)
            self.regime_analysis = payload.get("regime_analysis", None)
        self._update_display()

    def _update_display(self) -> None:
        self._update_summary_display()
        self._update_pivots_table()
        self._update_mispricings_table()
        self._update_strikes_table()
        self._update_updown_table()

    def _format_ts(self, value: Any) -> str:
        if not value:
            return "N/A"
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1e12:
                ts = ts / 1000
            try:
                return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            except (ValueError, OSError):
                return str(value)
        return str(value)

    def _update_summary_display(self) -> None:
        price = safe_float(self.strikes.get("price_approx"), 0)
        sentiment = self.summary.get("sentiment", "")
        up_prob = safe_float(self.summary.get("overall_up_probability"), 0)
        ts = self._format_ts(self.summary.get("timestamp"))

        title = f"📈 Polymarket • {self.selected_symbol} • ${price:,.0f}"
        if sentiment:
            title += f" • {sentiment}"
        self.query_one("#polyfull-title", Label).update(title)

        sentiment_lines = [
            f"  Window: {self.selected_window}",
            f"  Up prob: {up_prob:.1f}%",
            f"  Updated: {ts}",
        ]
        self.query_one("#polyfull-sentiment", Label).update("\n".join(sentiment_lines))

        pivot_count = 0
        pivots = self.pivots.get("pivots", {})
        if isinstance(pivots, dict):
            pivot_count = len(pivots)
        piv_lines = [
            f"  Count: {pivot_count}",
            f"  Updated: {self._format_ts(self.pivots.get('timestamp'))}",
        ]
        self.query_one("#polyfull-pivots-summary", Label).update("\n".join(piv_lines))

        dist_lines = []
        for interval in self.INTERVALS:
            dist = (self.distributions or {}).get(interval)
            if not dist:
                continue
            mean = safe_float(dist.get("mean"), 0)
            std = safe_float(dist.get("std"), 0)
            prob_pos = safe_float(dist.get("prob_positive"), 0)
            sample = dist.get("sample_size", "")
            dist_lines.append(
                f"  {interval}: μ {mean:+.2f} σ {std:.2f}  +{prob_pos:.1f}%  n={sample}"
            )
        if not dist_lines:
            dist_lines.append("  [dim]No distribution data[/dim]")
        self.query_one("#polyfull-distributions", Label).update("\n".join(dist_lines))

        regime_lines = []
        if isinstance(self.regime_analysis, dict) and self.regime_analysis:
            for key, value in self.regime_analysis.items():
                regime_lines.append(f"  {key}: {value}")
        else:
            regime_lines.append("  [dim]No regime analysis[/dim]")
        self.query_one("#polyfull-regime", Label).update("\n".join(regime_lines))

        status = ""
        if self.error_message:
            status = f"[red]Error:[/red] {self.error_message}"
        self.query_one("#polyfull-status", Label).update(status)

    def _update_pivots_table(self) -> None:
        table = self.query_one("#polyfull-pivots", DataTable)
        table.clear(columns=True)
        table.add_column("Pivot")
        table.add_column("Strike")
        table.add_column("Prob")

        pivots = self.pivots.get("pivots", {})
        if not isinstance(pivots, dict) or not pivots:
            table.add_row("No pivots", "", "")
            return

        for name, data in pivots.items():
            strike = data.get("strike") if isinstance(data, dict) else ""
            prob = data.get("probability") if isinstance(data, dict) else ""
            strike_str = f"{strike:,.0f}" if isinstance(strike, (int, float)) else str(strike)
            prob_str = fmt_pct(prob, decimals=1) if isinstance(prob, (int, float)) else str(prob)
            table.add_row(str(name), strike_str, prob_str)

    def _update_mispricings_table(self) -> None:
        table = self.query_one("#polyfull-mispricings", DataTable)
        table.clear(columns=True)
        columns = [
            ("resolution_date", "Date"),
            ("strike_price", "Strike"),
            ("distance_pct", "Dist %"),
            ("polymarket_prob", "PM %"),
            ("fair_prob", "Fair %"),
            ("edge", "Edge"),
            ("edge_pct", "Edge %"),
            ("verdict", "Verdict"),
        ]
        for _key, label in columns:
            table.add_column(label)

        if not self.mispricings or not self.mispricings.get("mispricings"):
            table.add_row("No mispricings", "", "", "", "", "", "", "")
            return

        items = self.mispricings.get("mispricings", [])
        for item in items[:100]:
            row = [
                str(item.get("resolution_date", "")),
                f"{safe_float(item.get('strike_price')):,.0f}",
                f"{safe_float(item.get('distance_pct')):.2f}%",
                f"{safe_float(item.get('polymarket_prob')):.2f}%",
                f"{safe_float(item.get('fair_prob')):.2f}%",
                f"{safe_float(item.get('edge')):.4f}",
                f"{safe_float(item.get('edge_pct')):.2f}%",
                str(item.get("verdict", "")),
            ]
            table.add_row(*row)

    def _update_strikes_table(self) -> None:
        table = self.query_one("#polyfull-strikes", DataTable)
        table.clear(columns=True)
        table.add_column("Date")
        table.add_column("Strike")
        table.add_column("Yes")
        table.add_column("Vol")
        table.add_column("Liq")
        table.add_column("Bid")
        table.add_column("Ask")
        table.add_column("Spread")

        strikes_by_date = self.strikes.get("strikes_by_date", {})
        if not isinstance(strikes_by_date, dict) or not strikes_by_date:
            table.add_row("No strikes", "", "", "", "", "", "", "")
            return

        rows = []
        for date, strikes in strikes_by_date.items():
            if not isinstance(strikes, list):
                continue
            for strike in strikes:
                rows.append((date, strike))

        for date, strike in rows[:120]:
            row = [
                str(date),
                f"{safe_float(strike.get('strike_price')):,.0f}",
                fmt_pct(strike.get("yes_price"), decimals=2),
                fmt_num(strike.get("volume"), decimals=2),
                fmt_num(strike.get("liquidity"), decimals=2),
                fmt_pct(strike.get("best_bid"), decimals=2),
                fmt_pct(strike.get("best_ask"), decimals=2),
                fmt_pct(strike.get("spread"), decimals=2),
            ]
            table.add_row(*row)

    def _update_updown_table(self) -> None:
        table = self.query_one("#polyfull-updown", DataTable)
        table.clear(columns=True)
        table.add_column("Interval")
        table.add_column("Count")
        table.add_column("Avg Up %")
        table.add_column("Markets")

        by_interval = self.summary.get("by_interval", {})
        markets_by_type = self.updown.get("markets_by_type", {})

        if not isinstance(by_interval, dict) or not by_interval:
            table.add_row("No summary", "", "", "")
            return

        for key, value in by_interval.items():
            if isinstance(value, dict):
                count = value.get("count", "")
                avg_up = value.get("avg_up_probability")
            else:
                count = ""
                avg_up = value
            market_count = ""
            if isinstance(markets_by_type, dict):
                markets = markets_by_type.get(key)
                if isinstance(markets, list):
                    market_count = len(markets)
                elif isinstance(markets, dict):
                    market_count = markets.get("count", "")
            table.add_row(
                str(key),
                str(count),
                fmt_pct(avg_up, decimals=2),
                str(market_count),
            )
