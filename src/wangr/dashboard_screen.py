"""Dashboard screen with card-based summaries."""

from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Button, Footer, Label, Static

from wangr.arbitrage import ArbitrageScreen
from wangr.base_screen import DataFetchingScreen
from wangr.chat_screen import ChatScreen
from wangr.config import MILLION
from wangr.liquidations import LiquidationsScreen
from wangr.market_brief import MarketBriefScreen
from wangr.polymarket_agent_screen import PolymarketAgentScreen
from wangr.polymarket_whales import PolymarketWhalesScreen
from wangr.settings import get_api_key, is_api_key_configured
from wangr.settings_screen import SettingsScreen
from wangr.sparkline import mini_bar
from wangr.utils import safe_division, safe_float
from wangr.whales_full import WhalesFullScreen
from wangr.widgets import LoadingSpinner
from wangr.woi_full import WOIFullScreen


class DashboardCard(Container):
    """Card widget with title, body, and open action."""

    def __init__(self, key: str, title: str) -> None:
        super().__init__(id=f"card-{key}", classes="dashboard-card")
        self.key = key
        self._title = Label(title, classes="dashboard-card-title")
        self._body = Static("", classes="dashboard-card-body")
        self._button = Button("Open", id=f"open-{key}", classes="dashboard-card-action")

    def compose(self) -> ComposeResult:
        yield self._title
        yield self._body
        yield self._button

    def set_body(self, text: str) -> None:
        """Update card body text."""
        self._body.update(text)

    def set_focused(self, focused: bool) -> None:
        """Set the focused state of this card."""
        if focused:
            self.add_class("card-focused")
        else:
            self.remove_class("card-focused")


class DashboardScreen(DataFetchingScreen):
    """Main dashboard screen showing card summaries."""

    MIN_CARD_WIDTH = 44
    BINDINGS = [
        ("left,h", "focus_prev", "Focus Previous"),
        ("right,l", "focus_next", "Focus Next"),
        ("up,k", "focus_up", "Focus Up"),
        ("down,j", "focus_down", "Focus Down"),
        ("enter", "open_focused", "Open Focused"),
        ("s", "open_settings", "Settings"),
    ]

    CARD_DEFS = [
        ("market-brief", "📊 Market Brief", MarketBriefScreen),
        ("whales", "🐋 Whales", WhalesFullScreen),
        ("woi", "🔍 Wallets of Interest", WOIFullScreen),
        ("liquidations", "💧 Liquidations", LiquidationsScreen),
        ("polymarket", "📈 Polymarket", PolymarketWhalesScreen),
        ("polymarket-agent", "🎯 Polymarket Agent", PolymarketAgentScreen),
        ("arbitrage", "📉 Arbitrage", ArbitrageScreen),
        ("chat", "🤖 Chat", ChatScreen),
    ]

    def __init__(self, data: dict) -> None:
        super().__init__(data)
        self._cards: dict[str, DashboardCard] = {}
        self._loaded_once = False
        self._focused_idx: int = 0

    def compose(self) -> ComposeResult:
        yield Footer()
        yield LoadingSpinner("Fetching market data", id="dashboard-loading", classes="dashboard-loading")
        cards = []
        for key, title, _screen in self.CARD_DEFS:
            card = DashboardCard(key, title)
            card.set_body("Loading...")
            self._cards[key] = card
            cards.append(card)
        yield Container(
            Container(*cards, id="dashboard-grid"),
            id="dashboard-wrapper",
        )

    async def on_mount(self) -> None:
        """Mount handler - start data fetching and size-aware layout."""
        await super().on_mount()
        self.call_after_refresh(self._update_grid_width)
        # Focus first card on mount
        self.call_after_refresh(lambda: self._set_focus_idx(0))

    def _set_focus_idx(self, idx: int) -> None:
        """Set focused card by index and update all visual states."""
        cards = list(self._cards.values())
        if not cards:
            return

        # Clamp index
        idx = max(0, min(len(cards) - 1, idx))
        self._focused_idx = idx

        # Update all card visuals
        for i, card in enumerate(cards):
            card.set_focused(i == idx)

        # Focus the button
        cards[idx].query_one(Button).focus()

    def on_screen_resume(self) -> None:
        """Restore focus state when returning to this screen."""
        self.call_after_refresh(lambda: self._set_focus_idx(self._focused_idx))

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        """Update card highlight when a button gets focus via click/tab."""
        widget = event.widget
        if isinstance(widget, Button) and widget.id and widget.id.startswith("open-"):
            key = widget.id.removeprefix("open-")
            keys = list(self._cards.keys())
            if key in keys:
                idx = keys.index(key)
                if idx != self._focused_idx:
                    self._focused_idx = idx
                    # Update visuals without re-focusing
                    for i, card in enumerate(self._cards.values()):
                        card.set_focused(i == idx)

    def on_resize(self, event: events.Resize) -> None:
        """Update layout on resize to respect width constraints."""
        self.call_after_refresh(self._update_grid_width)

    def _update_display(self) -> None:
        """Update all card summaries."""
        self._loaded_once = True
        try:
            banner = self.query_one("#dashboard-loading", LoadingSpinner)
            banner.display = False
        except Exception:
            pass
        self._cards["market-brief"].set_body(self._market_brief_summary())
        self._cards["whales"].set_body(self._whales_summary())
        self._cards["woi"].set_body(self._woi_summary())
        self._cards["liquidations"].set_body(self._liquidations_summary())
        self._cards["polymarket"].set_body(self._polymarket_summary())
        self._cards["polymarket-agent"].set_body(self._polymarket_agent_summary())
        self._cards["arbitrage"].set_body(self._arbitrage_summary())
        self._cards["chat"].set_body(self._chat_summary())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Open the screen associated with a card."""
        if not event.button.id or not event.button.id.startswith("open-"):
            return
        key = event.button.id.removeprefix("open-")

        # Update focus index to track which card was pressed
        self._focus_button_by_key(key)

        # Open the screen
        for card_key, _title, screen_cls in self.CARD_DEFS:
            if key == card_key:
                if card_key == "chat":
                    self._open_chat_with_key_check()
                elif card_key == "polymarket-agent":
                    self._open_polymarket_agent_with_key_check()
                elif card_key == "whales":
                    cache = getattr(self.app, "whales_full_cache", None)
                    self.app.push_screen(WhalesFullScreen(self.data, cache=cache))
                elif card_key == "woi":
                    cache = getattr(self.app, "woi_full_cache", None)
                    self.app.push_screen(WOIFullScreen(self.data, cache=cache))
                else:
                    if card_key == "arbitrage":
                        cache = getattr(self.app, "arb_cache", None)
                        self.app.push_screen(screen_cls(self.data, cache=cache))
                    else:
                        self.app.push_screen(screen_cls(self.data))
                break

    def _open_chat_with_key_check(self) -> None:
        """Open chat screen if API key is configured, otherwise show settings."""
        if is_api_key_configured():
            self.app.push_screen(ChatScreen())
        else:
            # Open settings with callback to open chat after key is validated
            self.app.push_screen(
                SettingsScreen(on_key_validated=self._on_api_key_validated)
            )

    def _on_api_key_validated(self) -> None:
        """Callback after API key is validated in settings."""
        # Pop the settings screen and open chat
        self.app.pop_screen()
        self.app.push_screen(ChatScreen())

    def _open_polymarket_agent_with_key_check(self) -> None:
        """Open Polymarket agent screen if API key is configured, otherwise show settings."""
        if is_api_key_configured():
            self.app.push_screen(PolymarketAgentScreen())
        else:
            self.app.push_screen(
                SettingsScreen(on_key_validated=self._on_polymarket_key_validated)
            )

    def _on_polymarket_key_validated(self) -> None:
        """Callback after API key is validated for Polymarket agent."""
        self.app.pop_screen()
        self.app.push_screen(PolymarketAgentScreen())

    def action_open_settings(self) -> None:
        """Open the settings screen."""
        self.app.push_screen(SettingsScreen())

    def action_open_whales_full(self) -> None:
        """Open the full whales table."""
        cache = getattr(self.app, "whales_full_cache", None)
        self.app.push_screen(WhalesFullScreen(self.data, cache=cache))

    def action_open_woi_full(self) -> None:
        """Open the full WOI table."""
        cache = getattr(self.app, "woi_full_cache", None)
        self.app.push_screen(WOIFullScreen(self.data, cache=cache))

    def action_focus_next(self) -> None:
        """Move focus to the next card."""
        self._focus_by_offset(1)

    def action_focus_prev(self) -> None:
        """Move focus to the previous card."""
        self._focus_by_offset(-1)

    def action_focus_down(self) -> None:
        """Move focus down one row."""
        self._focus_by_offset(self._columns())

    def action_focus_up(self) -> None:
        """Move focus up one row."""
        self._focus_by_offset(-self._columns())

    def action_open_focused(self) -> None:
        """Open the screen associated with the focused card."""
        focused = self.focused
        if isinstance(focused, Button) and focused.id and focused.id.startswith("open-"):
            focused.press()

    def _columns(self) -> int:
        """Return current column count."""
        grid = self.query_one("#dashboard-grid", Container)
        return max(1, int(grid.styles.grid_size_columns or 1))

    def _focus_by_offset(self, offset: int) -> None:
        """Focus a card action button by list offset."""
        new_idx = self._focused_idx + offset
        self._set_focus_idx(new_idx)

    def _focus_button_by_key(self, key: str) -> None:
        """Focus the Open button for a given card key."""
        keys = list(self._cards.keys())
        if key in keys:
            idx = keys.index(key)
            self._set_focus_idx(idx)

    def _update_grid_width(self) -> None:
        """Adjust grid width based on terminal size."""
        grid = self.query_one("#dashboard-grid", Container)
        width = self.size.width
        columns = max(1, min(3, width // self.MIN_CARD_WIDTH))

        if columns == 1:
            grid.styles.layout = "vertical"
            grid.styles.grid_size_columns = 1
            grid.styles.width = "100%"
        else:
            grid.styles.layout = "grid"
            grid.styles.grid_size_columns = columns
            grid.styles.width = "100%" if columns == 2 else "70%"

    def _market_brief_summary(self) -> str:
        btc = self.data.get("btc", {})
        eth = self.data.get("eth", {})
        sol = self.data.get("sol", {})
        if not (btc or eth or sol):
            return "Loading..."

        def fmt_coin(symbol: str, data: dict) -> str:
            price = safe_float(data.get("price"), 0)
            change = safe_float(data.get("change_24h_pct"), 0)
            arrow = "▲" if change >= 0 else "▼"
            color = "#90EE90" if change >= 0 else "#FF6B6B"
            return f"{symbol} ${price:>7,.0f}  [{color}]{arrow}{change:>+6.2f}%[/{color}]"

        return "\n".join([
            fmt_coin("₿", btc),
            fmt_coin("Ξ", eth),
            fmt_coin("◎", sol),
        ])

    def _whales_summary(self) -> str:
        def line(symbol: str, data: dict | None) -> str:
            data = data or {}
            count = data.get("count", 0)
            longs = data.get("long_count", 0)
            shorts = data.get("short_count", 0)
            total = max(longs + shorts, 1)
            bar = mini_bar(longs, total, width=12)
            return f"{symbol} {count:>3}  {bar}  {longs:>2}L {shorts:>2}S"

        if not (self.data.get("whales") or self.data.get("whales_eth") or self.data.get("whales_sol")):
            return "Loading..."
        return "\n".join([
            line("₿", self.data.get("whales", {})),
            line("Ξ", self.data.get("whales_eth", {})),
            line("◎", self.data.get("whales_sol", {})),
        ])

    def _woi_summary(self) -> str:
        agg = self.data.get("woi", {}).get("aggregates", {})
        if not agg:
            return "Loading..."
        total_pnl = safe_division(agg.get("total_realized_pnl", 0), MILLION)
        win_rate = agg.get("win_share", 0)
        trades = agg.get("total_trades", 0)
        longs = agg.get('long_count', 0)
        shorts = agg.get('short_count', 0)
        pnl_color = "#90EE90" if total_pnl >= 0 else "#FF6B6B"
        win_bar = mini_bar(win_rate, 100, width=12)
        return "\n".join([
            f"PnL     [{pnl_color}]${total_pnl:>6.2f}M[/{pnl_color}]",
            f"Win     {win_bar}  {win_rate:>3.0f}%",
            f"Trades  {trades:>5}   ↑{longs:>3} ↓{shorts:>3}",
        ])

    def _liquidations_summary(self) -> str:
        liq = self.data.get("liquidations", {})
        if not liq:
            return "Loading..."
        total_24h = safe_division(liq.get("total_usd_24h", 0), MILLION)
        long_24h = safe_division(liq.get("total_long_usd_24h", 0), MILLION)
        short_24h = safe_division(liq.get("total_short_usd_24h", 0), MILLION)
        total = max(long_24h + short_24h, 1)
        long_bar = mini_bar(long_24h, total, width=12)
        short_bar = mini_bar(short_24h, total, width=12)
        return "\n".join([
            f"24h  [bold]${total_24h:>6.1f}M[/bold]",
            f"↑    {long_bar}  ${long_24h:>5.1f}M",
            f"↓    {short_bar}  ${short_24h:>5.1f}M",
        ])

    def _polymarket_summary(self) -> str:
        poly = self.data.get("polymarket", {})
        if not poly:
            return "Loading..."
        traders = poly.get("traders_tracked", 0)
        total_pnl = safe_division(poly.get("total_pnl", 0), MILLION)
        total_vol = safe_division(poly.get("total_recent_volume", 0), MILLION)
        pnl_color = "#90EE90" if total_pnl >= 0 else "#FF6B6B"
        return "\n".join([
            f"Traders  [bold]{traders:>6,}[/bold]",
            f"PnL      [{pnl_color}]${total_pnl:>6.2f}M[/{pnl_color}]",
            f"Volume   ${total_vol:>6.2f}M",
        ])

    def _polymarket_agent_summary(self) -> str:
        if is_api_key_configured():
            return "AI agent for Polymarket\n[dim]Markets, events, traders[/dim]\n[dim]Streaming responses[/dim]"
        return "[yellow]API key required[/yellow]\n[dim]Press S for Settings[/dim]\n[dim]to get started[/dim]"

    def _chat_summary(self) -> str:
        if is_api_key_configured():
            return "AI-powered market analysis\n[dim]Ask about whales, WOI[/dim]\n[dim]prices, positions...[/dim]"
        return "[yellow]API key required[/yellow]\n[dim]Press S for Settings[/dim]\n[dim]to get started[/dim]"

    def _arbitrage_summary(self) -> str:
        spot = self.data.get("arbitrage", {}).get("spot", {})
        futures = self.data.get("arbitrage", {}).get("futures", {})
        dex = self.data.get("arbitrage", {}).get("dex", {})
        if not (spot or futures or dex):
            return "Loading..."
        spot_spread = safe_float(spot.get("net_spread_pct"), 0)
        futures_spread = safe_float(futures.get("net_after_funding_pct"), 0)
        dex_spread = safe_float(dex.get("spread_pct"), 0)

        def fmt_arb(label: str, spread: float) -> str:
            if spread > 0.1:
                icon = "[#90EE90]✓[/#90EE90]"
                color = "#90EE90"
            elif spread > 0:
                icon = "[#FFD700]•[/#FFD700]"
                color = "#FFD700"
            else:
                icon = "[dim]•[/dim]"
                color = "dim"
            return f"{icon} {label:<8} [{color}]{spread:>+6.2f}%[/{color}]"

        return "\n".join([
            fmt_arb("Spot", spot_spread),
            fmt_arb("Futures", futures_spread),
            fmt_arb("DEX", dex_spread),
        ])
