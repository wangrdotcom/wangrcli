# Wangr TUI - Complete Implementation Guide

A comprehensive technical reference for the Wangr cryptocurrency market intelligence terminal dashboard.

---

## Table of Contents

1. [Overview](#overview)
2. [Dependencies](#dependencies)
3. [Entry Point: main.py](#entry-point-mainpy)
4. [Configuration: config.py](#configuration-configpy)
5. [Data Layer: data.py](#data-layer-datapy)
6. [Utility Functions: utils.py](#utility-functions-utilspy)
7. [Base Screen Pattern: base_screen.py](#base-screen-pattern-base_screenpy)
8. [Dashboard Screen: dashboard_screen.py](#dashboard-screen-dashboard_screenpy)
9. [Detail Screens](#detail-screens)
   - [Market Brief: market_brief.py](#market-brief-market_briefpy)
   - [Whales: whales.py](#whales-whalespy)
   - [Whales Full: whales_full.py](#whales-full-whales_fullpy)
   - [WOI: woi.py](#woi-woipy)
   - [WOI Full: woi_full.py](#woi-full-woi_fullpy)
   - [Liquidations: liquidations.py](#liquidations-liquidationspy)
   - [Polymarket: polymarket.py](#polymarket-polymarketpy)
   - [Arbitrage: arbitrage.py](#arbitrage-arbitragepy)
10. [Chat Screen: chat_screen.py](#chat-screen-chat_screenpy)
11. [Sort Modal: sort_modal.py](#sort-modal-sort_modalpy)
12. [Styling: dashboard.tcss](#styling-dashboardtcss)
13. [Data Flow Diagram](#data-flow-diagram)
14. [Keyboard Bindings Reference](#keyboard-bindings-reference)

---

## Overview

Wangr TUI is a terminal-based dashboard for cryptocurrency market intelligence built with Python's Textual framework. It provides real-time data visualization for:

- **Whale positions** (BTC, ETH, SOL) - Large trader tracking
- **Wallets of Interest (WOI)** - Tracked profitable wallets
- **Liquidations** - Exchange liquidation statistics
- **Polymarket** - Prediction market trader stats
- **Arbitrage** - Spot/Futures/DEX spread opportunities
- **AI Chat** - Interactive assistant for market queries

---

## Dependencies

From `pyproject.toml`:

```toml
[project]
name = "tui-dashboard"
requires-python = ">=3.14"
dependencies = [
    "requests>=2.32.5",      # HTTP client for API calls
    "textual>=6.11.0",       # TUI framework
    "textual-dev>=1.8.0",    # Textual development tools
]
```

### Key Textual Imports Used

| Import | Purpose |
|--------|---------|
| `textual.app.App` | Main application class |
| `textual.screen.Screen` | Base class for screens |
| `textual.screen.ModalScreen` | Base for modal dialogs |
| `textual.worker.Worker` | Background task execution |
| `textual.reactive.reactive` | Reactive state management |
| `textual.widgets.*` | UI components (Label, Button, DataTable, etc.) |
| `textual.containers.*` | Layout containers (Container, Horizontal, VerticalScroll) |

---

## Entry Point: main.py

**File:** `main.py` (46 lines)

The application entry point that initializes the Textual app and manages global state.

### Class: `DashboardApp(App)`

```python
class DashboardApp(App):
    CSS_PATH = "dashboard.tcss"  # Links to stylesheet
    BINDINGS = [
        ("d", "toggle_dark", "Toggle dark mode"),
        ("q", "quit", "Quit the app"),
    ]
```

### Lifecycle Methods

#### `on_mount(self) -> None`

Called when the app starts. Performs three critical tasks:

1. **Initializes cache dictionaries** on the app instance:
   ```python
   self.whales_full_cache = {}  # Stores whale data for BTC/ETH/SOL
   self.woi_full_cache = {}     # Stores WOI tracked users
   ```

2. **Spawns background workers** to preload heavy data:
   ```python
   self.run_worker(fetch_whales_full_data, thread=True, name="preload_whales_full")
   self.run_worker(fetch_woi_full_data, thread=True, name="preload_woi_full")
   ```

3. **Pushes the initial screen**:
   ```python
   self.push_screen(DashboardScreen({}))  # Empty dict - data loads async
   ```

#### `on_worker_state_changed(self, event: Worker.StateChanged) -> None`

Handles worker completion events:

```python
def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
    if event.state.name != "SUCCESS":
        return
    if event.worker.name == "preload_whales_full":
        self.whales_full_cache = event.worker.result
    elif event.worker.name == "preload_woi_full":
        self.woi_full_cache = event.worker.result
```

### Startup Sequence

```
main.py executed
    └── DashboardApp() instantiated
        └── on_mount() called
            ├── Initialize empty cache dicts
            ├── Start preload_whales_full worker (background thread)
            ├── Start preload_woi_full worker (background thread)
            └── Push DashboardScreen({}) to screen stack
                └── DashboardScreen.on_mount() triggers its own data fetch
```

---

## Configuration: config.py

**File:** `config.py` (23 lines)

Centralized configuration constants using `typing.Final` for immutability.

### API Endpoints

```python
FRONTPAGE_API_URL: Final[str] = "https://polymarket-api.wangr.com/frontpage/"
BTC_WHALES_API_URL: Final[str] = "https://api3.wangr.com/whales"
ETH_WHALES_API_URL: Final[str] = "https://ethwhalesapi.wangr.com/whales"
SOL_WHALES_API_URL: Final[str] = "https://solwhalesapi.wangr.com/whales"
CHAT_API_URL: Final[str] = "https://agent.wangr.com/chat"
WOI_TRACKED_USERS_API_URL: Final[str] = "https://api2899.wangr.com/woi/tracked-users?limit=400"
```

### Timing Constants

```python
API_TIMEOUT: Final[int] = 10        # Seconds before request times out
FETCH_INTERVAL: Final[float] = 60.0  # Seconds between periodic refreshes
```

### Display Constants

```python
BAR_WIDTH: Final[int] = 50               # Width of horizontal bar charts
PRICE_FORMAT_THRESHOLD: Final[int] = 20000  # Above this, show as "$XXk"
MILLION: Final[int] = 1_000_000
THOUSAND: Final[int] = 1_000
```

---

## Data Layer: data.py

**File:** `data.py` (89 lines)

Provides API fetch functions used throughout the application.

### Function: `fetch_dashboard_data() -> dict`

Fetches the main dashboard data from the frontpage API.

```python
def fetch_dashboard_data() -> dict:
    try:
        response = requests.get(FRONTPAGE_API_URL, timeout=API_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error fetching data from {FRONTPAGE_API_URL}: {e}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON from {FRONTPAGE_API_URL}: {e}")
        return {}
```

**Returns:** Dictionary containing keys like `btc`, `eth`, `sol`, `whales`, `whales_eth`, `whales_sol`, `woi`, `liquidations`, `polymarket`, `arbitrage`, `sentiment`.

### Function: `fetch_whales_full_data() -> dict`

Fetches detailed whale data for all three coins in sequence.

```python
def fetch_whales_full_data() -> dict:
    def fetch(url: str) -> list:
        # Fetches and returns active_whales[:30]
        ...

    return {
        "whales_btc": fetch(BTC_WHALES_API_URL),
        "whales_eth": fetch(ETH_WHALES_API_URL),
        "whales_sol": fetch(SOL_WHALES_API_URL),
    }
```

**Returns:** Dictionary with `whales_btc`, `whales_eth`, `whales_sol` lists (max 30 each).

### Function: `fetch_woi_full_data() -> dict`

Fetches tracked WOI users.

```python
def fetch_woi_full_data() -> dict:
    try:
        resp = requests.get(WOI_TRACKED_USERS_API_URL, timeout=API_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return {"users": data.get("users", [])}
    except ...:
        return {"users": []}
```

**Returns:** Dictionary with `users` list.

---

## Utility Functions: utils.py

**File:** `utils.py` (121 lines)

Helper functions for data formatting and safe value handling.

### Function: `format_bar(left, right, val_l, val_r, width=50) -> str`

Creates a horizontal bar chart comparing two values.

```python
def format_bar(left: str, right: str, val_l: float, val_r: float, width: int = 50) -> str:
    total = val_l + val_r
    pct = int((val_l / total * width)) if total > 0 else width // 2
    bar = f"{'█' * pct}{'░' * (width - pct)}"
    return f"{left:<20} {bar} {right:>20}"
```

**Example output:**
```
L:45                 ██████████████████████████████████░░░░░░░░░░░░░░░                    S:25
```

### Function: `safe_division(numerator, denominator, default=0.0) -> float`

Prevents division by zero errors.

```python
def safe_division(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0:
        return default
    return numerator / denominator
```

### Function: `format_price(price, threshold=20000) -> str`

Formats prices with "k" suffix for large values.

```python
def format_price(price: float, threshold: float = 20000) -> str:
    if price >= threshold:
        return f"${price/THOUSAND:.1f}k"  # e.g., "$95.2k"
    return f"${price:.2f}"                 # e.g., "$185.50"
```

### Function: `safe_float(value, default=0.0) -> float`

Safely converts any value to float.

```python
def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default
```

### Function: `safe_get_nested(data, *keys, default=None) -> Any`

Safely traverses nested dictionaries.

```python
def safe_get_nested(data: dict, *keys: str, default: Any = None) -> Any:
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
        if current is default:
            return default
    return current
```

**Usage:** `safe_get_nested(data, "arbitrage", "spot", "spread_pct")`

### Function: `format_time(minutes) -> str`

Converts minutes to human-readable duration.

```python
def format_time(minutes: float) -> str:
    if minutes < 60:
        return f"{minutes:.0f}m"    # "45m"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:.1f}h"      # "2.5h"
    days = hours / 24
    return f"{days:.1f}d"           # "3.2d"
```

---

## Base Screen Pattern: base_screen.py

**File:** `base_screen.py` (128 lines)

Abstract base class implementing the periodic data-fetching pattern used by most screens.

### Class: `DataFetchingScreen(Screen)`

```python
class DataFetchingScreen(Screen):
    FETCH_URL: str = FRONTPAGE_API_URL  # Override in subclasses
    FETCH_INTERVAL: float = FETCH_INTERVAL  # 60 seconds default

    def __init__(self, data: dict) -> None:
        super().__init__()
        self.data = data                        # Initial data dict
        self.update_timer: Optional[Any] = None # Timer reference
        self._current_worker: Optional[Worker] = None  # Active worker
```

### Lifecycle Methods

#### `on_mount(self) -> None`

Called when screen becomes visible:

```python
async def on_mount(self) -> None:
    self._update_display()  # Show initial data immediately
    self._schedule_fetch()  # Start periodic fetching
```

#### `on_unmount(self) -> None`

Cleanup when screen is removed:

```python
def on_unmount(self) -> None:
    if self.update_timer:
        self.update_timer.stop()
        self.update_timer = None
    if self._current_worker and self._current_worker.is_running:
        self._current_worker.cancel()
        self._current_worker = None
```

### Data Fetching Methods

#### `_schedule_fetch(self) -> None`

Initiates periodic data refresh:

```python
def _schedule_fetch(self) -> None:
    self._fetch_data()  # Fetch immediately
    self.update_timer = self.set_interval(self.FETCH_INTERVAL, self._fetch_data)
```

#### `_fetch_data(self) -> None`

Spawns a background worker for API calls:

```python
def _fetch_data(self) -> None:
    # Prevent duplicate workers
    if self._current_worker and self._current_worker.is_running:
        return

    worker_name = f"data_fetch_{self.__class__.__name__}_{id(self)}"
    self._current_worker = self.run_worker(
        self._fetch_dashboard_data,
        thread=True,
        name=worker_name
    )
```

#### `_fetch_dashboard_data(self) -> dict`

The actual API call (runs in background thread):

```python
def _fetch_dashboard_data(self) -> dict:
    try:
        resp = requests.get(self.FETCH_URL, timeout=API_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch data from {self.FETCH_URL}: {e}")
        return {}
```

### Worker Callback

#### `on_worker_state_changed(self, event: Worker.StateChanged) -> None`

Handles worker completion:

```python
def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
    if (event.worker == self._current_worker and
            event.state.name == "SUCCESS"):
        new_data = event.worker.result
        if new_data:
            self._process_new_data(new_data)
            self._update_display()
```

### Abstract Methods (Override in Subclasses)

```python
def _process_new_data(self, new_data: dict) -> None:
    """Extract relevant data from API response."""
    self.data = new_data  # Default: store entire response

def _update_display(self) -> None:
    """Update UI with current data. MUST be implemented."""
    raise NotImplementedError("Subclasses must implement _update_display()")
```

### Navigation

```python
def action_go_back(self) -> None:
    """Navigate back to previous screen."""
    self.app.pop_screen()
```

---

## Dashboard Screen: dashboard_screen.py

**File:** `dashboard_screen.py` (283 lines)

The main hub displaying summary cards for all data categories.

### Class: `DashboardCard(Container)`

A reusable card widget with title, body, and action button.

```python
class DashboardCard(Container):
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
        self._body.update(text)
```

### Class: `DashboardScreen(DataFetchingScreen)`

```python
class DashboardScreen(DataFetchingScreen):
    MIN_CARD_WIDTH = 44  # Minimum card width for responsive layout

    BINDINGS = [
        ("left,h", "focus_prev", "Focus Previous"),
        ("right,l", "focus_next", "Focus Next"),
        ("up,k", "focus_up", "Focus Up"),
        ("down,j", "focus_down", "Focus Down"),
        ("enter", "open_focused", "Open Focused"),
        ("w", "open_whales_full", "Whales Full"),
        ("o", "open_woi_full", "WOI Full"),
    ]
```

### Card Definitions

```python
CARD_DEFS = [
    ("market-brief", "Market Brief", MarketBriefScreen),
    ("whales", "Whales", WhalesScreen),
    ("woi", "Wallets of Interest", WOIScreen),
    ("liquidations", "Liquidations", LiquidationsScreen),
    ("polymarket", "Polymarket", PolymarketScreen),
    ("arbitrage", "Arbitrage", ArbitrageScreen),
    ("chat", "Chat", ChatScreen),
]
```

### UI Composition

```python
def compose(self) -> ComposeResult:
    yield Header()
    yield Footer()
    yield Static("Loading data...", id="dashboard-loading")
    cards = []
    for key, title, _screen in self.CARD_DEFS:
        card = DashboardCard(key, title)
        self._cards[key] = card
        cards.append(card)
    yield Container(
        Container(*cards, id="dashboard-grid"),
        id="dashboard-wrapper",
    )
```

### Responsive Grid Layout

Adjusts columns based on terminal width:

```python
def _update_grid_width(self) -> None:
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
```

### Card Summary Methods

Each card has a dedicated summary method:

```python
def _market_brief_summary(self) -> str:
    btc = self.data.get("btc", {})
    eth = self.data.get("eth", {})
    sol = self.data.get("sol", {})
    return "\n".join([
        f"BTC ${safe_float(btc.get('price'), 0):,.0f} ({safe_float(btc.get('change_24h_pct'), 0):+.2f}%)",
        f"ETH ${safe_float(eth.get('price'), 0):,.0f} ({safe_float(eth.get('change_24h_pct'), 0):+.2f}%)",
        f"SOL ${safe_float(sol.get('price'), 0):,.0f} ({safe_float(sol.get('change_24h_pct'), 0):+.2f}%)",
    ])

def _whales_summary(self) -> str:
    # Returns: "BTC: 45 L:25 S:20\nETH: 32 L:18 S:14\nSOL: 28 L:15 S:13"

def _woi_summary(self) -> str:
    # Returns: "Total PnL: $2.45M\nWin Rate: 65.2%  Trades: 1234\nLongs: 45  Shorts: 32"

def _liquidations_summary(self) -> str:
    # Returns: "Total 24h: $125.50M\nLongs: $80.25M\nShorts: $45.25M"

def _polymarket_summary(self) -> str:
    # Returns: "Traders: 1,234\nTotal PnL: $5.67M\nVolume: $12.34M"

def _arbitrage_summary(self) -> str:
    # Returns: "Spot: +0.25%\nFutures: +0.18%\nDEX: +0.42%"
```

### Navigation Actions

```python
def on_button_pressed(self, event: Button.Pressed) -> None:
    key = event.button.id.removeprefix("open-")
    for card_key, _title, screen_cls in self.CARD_DEFS:
        if key == card_key:
            if card_key == "chat":
                self.app.push_screen(ChatScreen())  # No data param
            else:
                self.app.push_screen(screen_cls(self.data))
            break

def action_open_whales_full(self) -> None:
    cache = getattr(self.app, "whales_full_cache", None)
    self.app.push_screen(WhalesFullScreen(self.data, cache=cache))

def action_open_woi_full(self) -> None:
    cache = getattr(self.app, "woi_full_cache", None)
    self.app.push_screen(WOIFullScreen({"users": cache.get("users", [])} if cache else {}))
```

### Grid Navigation

```python
def _focus_by_offset(self, offset: int) -> None:
    buttons = [card.query_one(Button) for card in self._cards.values()]
    if self.focused in buttons:
        idx = buttons.index(self.focused)
    else:
        idx = 0
    idx = max(0, min(len(buttons) - 1, idx + offset))
    buttons[idx].focus()

def action_focus_down(self) -> None:
    self._focus_by_offset(self._columns())  # Jump by column count
```

---

## Detail Screens

### Market Brief: market_brief.py

**File:** `market_brief.py` (93 lines)

Displays cryptocurrency prices and market sentiment.

#### Widgets

**`CoinPrices(Container)`** - Shows BTC/ETH/SOL prices with 24h changes using `Digits` widget.

```python
class CoinPrices(Container):
    def __init__(self, data: dict) -> None:
        super().__init__()
        btc = data.get("btc", {})
        self.btc_price = str(safe_float(btc.get("price"), 0))
        self.btc_change_24h_pct = safe_float(btc.get("change_24h_pct"), 0.0)
        # ... same for ETH and SOL

    def compose(self) -> ComposeResult:
        btc_change_class = "change-positive" if self.btc_change_24h_pct >= 0 else "change-negative"
        yield HorizontalGroup(
            Label("BTC"),
            Label(f"{self.btc_change_24h_pct:+.2f}%", classes=btc_change_class),
            Digits(self.btc_price),
            # ... ETH, SOL
        )
```

**`SentimentInfo(Container)`** - Shows sentiment analysis (value, post count, summaries).

```python
class SentimentInfo(Container):
    def compose(self) -> ComposeResult:
        yield Label(f"Overall Sentiment: {self.sentiment}")
        yield Label(f"Post Count: {self.post_count}")
        yield Label(self.summary, classes="summary-text")
        yield Label(self.bullish_summary, classes="bullish-text")
        yield Label(self.bearish_summary, classes="bearish-text")
```

#### Screen Class

```python
class MarketBriefScreen(DataFetchingScreen):
    BINDINGS = [("b", "go_back", "Go Back")]

    def _update_display(self) -> None:
        scroll = self.query_one("#content-scroll", VerticalScroll)
        scroll.remove_children()
        scroll.mount(CoinPrices(self.data))
        scroll.mount(SentimentInfo(self.data.get("sentiment", {})))
```

---

### Whales: whales.py

**File:** `whales.py` (282 lines)

Summary view of whale positions with coin selection tabs.

#### Reactive State

```python
class WhalesScreen(DataFetchingScreen):
    selected_coin: reactive[str] = reactive("BTC")  # Triggers watch_selected_coin

    def watch_selected_coin(self, new_coin: str) -> None:
        self._update_coin_classes(new_coin)
        self._update_display()
```

#### Coin Selection UI

```python
def compose(self) -> ComposeResult:
    yield Header()
    yield Footer()
    yield Horizontal(
        Static("BTC", id="coin-btc", classes="coin-toggle coin-toggle-active"),
        Static("ETH", id="coin-eth", classes="coin-toggle"),
        Static("SOL", id="coin-sol", classes="coin-toggle"),
        id="whale-coins",
    )
    yield Container(
        Label("", id="whale-title"),
        Label("", id="whale-bar-1"),  # Long vs Short count
        Label("", id="whale-bar-2"),  # Long vs Short size
        Label("", id="whale-bar-3"),  # Long vs Short notional
        # ... metrics
    )
```

#### Data Processing

```python
def _process_new_data(self, new_data: dict) -> None:
    super()._process_new_data(new_data)
    self.whales_btc = new_data.get("whales", {})
    self.whales_eth = new_data.get("whales_eth", {})
    self.whales_sol = new_data.get("whales_sol", {})
    self.btc_price = safe_float(new_data.get("btc", {}).get("price"), 0)
    # ... ETH, SOL prices
```

#### PnL Calculation

```python
def _calc_long_pnl_pct(self, entry: float) -> str:
    price = self._get_current_price()
    if entry == 0 or price == 0:
        return ""
    pct = safe_division(price - entry, entry) * 100
    return f"{pct:+.1f}%"

def _calc_short_pnl_pct(self, entry: float) -> str:
    price = self._get_current_price()
    pct = safe_division(entry - price, entry) * 100  # Inverted for shorts
    return f"{pct:+.1f}%"
```

#### Display Metrics

```python
def _metric(self, label: str, lval: str, lpct: str, sval: str, spct: str) -> str:
    # Color code percentages
    if lpct.startswith("+"):
        lpct_colored = f"[green]{lpct}[/green]"
    elif lpct.startswith("-"):
        lpct_colored = f"[red]{lpct}[/red]"
    return f"{label:12} L {lval:>8} {lpct_colored:>15}  S {sval:>8} {spct_colored:>15}"
```

---

### Whales Full: whales_full.py

**File:** `whales_full.py` (476 lines)

Full sortable DataTable of whale positions.

**Note:** Does NOT inherit from `DataFetchingScreen` - implements its own multi-endpoint fetching.

#### Column Definitions

```python
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
```

#### Multi-Endpoint Fetching

```python
def _fetch_all_whale_data(self) -> None:
    """Fetch whale data for all coins in parallel."""
    if not (self._btc_worker and self._btc_worker.is_running):
        self._btc_worker = self.run_worker(
            partial(self._fetch_whale_data, BTC_WHALES_API_URL),
            name="btc", thread=True
        )
    # ... same for ETH and SOL workers
```

#### Sorting Implementation

```python
def _sort_whales(self, whales: list, price: float) -> list:
    def get_sort_key(whale: dict):
        pos = whale.get("position") or {}
        stats = whale.get("initial_stats") or {}

        if self.sort_column == "size":
            return safe_float(whale.get("size"), 0)
        elif self.sort_column == "upnl_pct":
            entry = safe_float(pos.get("entry_px"), 0)
            side = whale.get("side", "")
            if entry > 0 and price > 0:
                if side == "LONG":
                    return safe_division(price - entry, entry) * 100
                else:
                    return safe_division(entry - price, entry) * 100
            return 0
        # ... other columns

    return sorted(whales, key=get_sort_key, reverse=self.sort_reverse)
```

#### Vim-Style gg Jump

```python
def on_key(self, event: events.Key) -> None:
    """Handle vim-style gg jump."""
    if event.key == "g":
        event.prevent_default()
        if self._pending_g:
            self._pending_g = False
            self._g_timer.stop()
            self.action_cursor_top()  # Jump to top
        else:
            self._pending_g = True
            self._g_timer = self.set_timer(0.5, self._clear_pending_g)
```

#### Cache Synchronization

```python
def _update_cache(self) -> None:
    """Cache latest whales lists on the app."""
    if hasattr(self.app, "whales_full_cache"):
        self.app.whales_full_cache = {
            "whales_btc": self.whales_btc,
            "whales_eth": self.whales_eth,
            "whales_sol": self.whales_sol,
        }
```

---

### WOI: woi.py

**File:** `woi.py` (89 lines)

Summary view of Wallets of Interest statistics.

```python
class WOIScreen(DataFetchingScreen):
    def _update_display(self) -> None:
        agg = self.woi.get("aggregates", {})
        top_wr = self.woi.get("top_3_by_win_rate", [])
        top_pnl = self.woi.get("top_3_by_pnl", [])

        # Build UI with format_bar and format_time
        main.mount(Container(
            Label("Wallets of Interest"),
            Label(f"Total PnL: ${total_pnl:.2f}M  |  Win Rate: {agg.get('win_share', 0):.1f}%"),
            Label(format_bar(f"Long: {agg.get('long_count', 0)}", f"Short: {agg.get('short_count', 0)}", ...)),
            Label(f"Avg Hold: {format_time(agg.get('average_hold_minutes', 0))}"),
            Label(wallets_text),
        ))
```

---

### WOI Full: woi_full.py

**File:** `woi_full.py` (265 lines)

Full sortable DataTable of tracked WOI users.

```python
class WOIFullScreen(DataFetchingScreen):
    FETCH_URL = WOI_TRACKED_USERS_API_URL  # Override default URL

    COLUMN_DEFS = [
        ("wallet", "Wallet"),
        ("total_positions", "Positions"),
        ("winning_positions", "Wins"),
        ("win_rate", "Win Rate"),
        ("total_realized_pnl", "Realized PnL"),
        ("first_open_time", "First Open"),
        ("last_close_time", "Last Close"),
        ("long_count", "Longs"),
        ("short_count", "Shorts"),
        ("avg_hold_minutes", "Avg Hold"),
        ("symbols_count", "Symbols"),
    ]
```

#### Timestamp Formatting

```python
def _format_ts(self, ts_ms: float) -> str:
    """Format epoch milliseconds to YYYY-MM-DD."""
    if not ts_ms:
        return "N/A"
    try:
        return datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return "N/A"
```

---

### Liquidations: liquidations.py

**File:** `liquidations.py` (97 lines)

Displays liquidation statistics across exchanges.

```python
class LiquidationsScreen(DataFetchingScreen):
    def _update_display(self) -> None:
        by_exchange = self.liqs.get("by_exchange", {})

        exchange_text = "By Exchange (24h):\n"
        for name, data in by_exchange.items():
            l_usd = safe_division(data.get("long_total_usd", 0), MILLION)
            s_usd = safe_division(data.get("short_total_usd", 0), MILLION)
            exchange_text += f"  {name.upper():12} L:${l_usd:>5.1f}M  S:${s_usd:>5.1f}M\n"
```

---

### Polymarket: polymarket.py

**File:** `polymarket.py` (123 lines)

Displays Polymarket prediction market trader statistics.

```python
class PolymarketScreen(DataFetchingScreen):
    def _update_display(self) -> None:
        traders = self.poly.get("traders_tracked", 0)
        whales = self.poly.get("whale_count", 0)
        profitable = self.poly.get("profitable_count", 0)
        losing = self.poly.get("losing_count", 0)

        # Profit/Loss bar
        format_bar(
            f"Profit:{profitable} ({profit_pct:.1f}%)",
            f"Loss:{losing} ({100-profit_pct:.1f}%)",
            profitable, losing
        )
```

---

### Arbitrage: arbitrage.py

**File:** `arbitrage.py` (87 lines)

Displays arbitrage opportunities across spot, futures, and DEX markets.

```python
class ArbitrageScreen(DataFetchingScreen):
    def _update_display(self) -> None:
        spot = self.arb.get("spot", {})
        futures = self.arb.get("futures", {})
        dex = self.arb.get("dex", {})

        spot_text = "SPOT ARBITRAGE\n"
        spot_text += f"  {spot.get('symbol')} Buy: {spot.get('buy_exchange')} → Sell: {spot.get('sell_exchange')}\n"
        spot_text += f"  Net Spread: {spot.get('net_spread_pct', 0):>6.2f}%"

        dex_text = "DEX ARBITRAGE\n"
        status = "✓ YES" if dex.get('arbitrage', False) else "✗ NO"
        dex_text += f"  Arbitrage: {status}"
```

---

## Chat Screen: chat_screen.py

**File:** `chat_screen.py` (265 lines)

Interactive AI chat interface. Does NOT inherit from `DataFetchingScreen`.

### State Management

```python
class ChatScreen(Screen):
    def __init__(self) -> None:
        super().__init__()
        self._history: list[dict[str, Any]] = []   # API conversation history
        self._entries: list[dict[str, Any]] = []   # Display entries
        self._worker: Worker | None = None
        self._processing_timer = None
        self._processing_frame = 0
        self._pending_index: int | None = None     # Processing placeholder index
```

### UI Composition

```python
def compose(self) -> ComposeResult:
    yield Header()
    yield Footer()
    yield Container(
        RichLog(id="chat-log", wrap=True, highlight=True, markup=True),
        Static("", id="chat-status"),
        Input(placeholder="Ask Wangr…", id="chat-input"),
        id="chat-container",
    )
```

### Chat Request

```python
def _chat_request(self, message: str) -> tuple[str, list[dict[str, Any]]]:
    response = requests.post(
        CHAT_API_URL,
        json={"message": message, "history": self._history},
        timeout=API_TIMEOUT * 12,  # 120 second timeout for AI responses
    )
    data = response.json()
    reply = data.get("response", "")
    tool_calls = data.get("tool_calls", [])

    # Update history
    self._history.append({"role": "user", "content": message})
    self._history.append({"role": "assistant", "content": reply})

    return reply, tool_calls
```

### Processing Animation

```python
def _start_processing(self) -> None:
    self._processing_frame = 0
    self._append_processing_placeholder()
    self._processing_timer = self.set_interval(0.4, self._tick_processing)

def _tick_processing(self) -> None:
    self._processing_frame = (self._processing_frame + 1) % 4
    if self._pending_index is not None:
        self._entries[self._pending_index]["content"] = self._processing_text()
        self._render_entries()

def _processing_text(self) -> str:
    spinner = ["|", "/", "-", "\\"]
    return f"Processing {spinner[self._processing_frame % len(spinner)]}"
```

### State Persistence

```python
def _restore_state(self) -> None:
    self._history = getattr(self.app, "chat_history", [])
    self._entries = getattr(self.app, "chat_entries", [])

def _persist_state(self) -> None:
    self.app.chat_history = self._history
    self.app.chat_entries = self._entries
```

---

## Sort Modal: sort_modal.py

**File:** `sort_modal.py` (94 lines)

Modal dialog for selecting sort column and direction.

### Class: `SortModal(ModalScreen[dict | None])`

```python
class SortModal(ModalScreen[dict | None]):
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("b", "cancel", "Cancel"),
        ("enter", "confirm", "Confirm"),
        ("S", "toggle_direction", "Toggle Direction"),
        ("down,j", "cursor_down", "Down"),
        ("up,k", "cursor_up", "Up"),
    ]

    def __init__(self, columns: list[tuple[str, str]], current_key: str | None, sort_reverse: bool):
        self.columns = columns
        self.sort_reverse = sort_reverse
        # Find initial index from current_key
```

### Return Value

```python
def _dismiss_with_selection(self) -> None:
    list_view = self.query_one("#sort-list", ListView)
    index = list_view.index or 0
    key = self.columns[index][0]
    self.dismiss({"key": key, "reverse": self.sort_reverse})  # dict or None
```

### Usage Pattern

```python
# In WhalesFullScreen or WOIFullScreen:
def action_sort_by_column(self) -> None:
    self.app.push_screen(
        SortModal(self.COLUMN_DEFS, self.sort_column, self.sort_reverse),
        self._on_sort_selected,  # Callback when modal closes
    )

def _on_sort_selected(self, result: dict | None) -> None:
    if not result:
        return
    self.sort_column = result.get("key")
    self.sort_reverse = result.get("reverse", self.sort_reverse)
    self._update_whale_display()
```

---

## Styling: dashboard.tcss

**File:** `dashboard.tcss` (400 lines)

Textual CSS for all screen styling.

### Design Tokens

Uses Textual's built-in design tokens:
- `$surface` - Background color
- `$primary` - Primary accent (borders, titles)
- `$accent` - Secondary accent (summaries)
- `$success` - Green (positive values, bars)
- `$error` - Red (negative values)
- `$warning` - Yellow (warnings, wallets)
- `$text` - Default text color
- `$panel` - Panel backgrounds

### Key Selectors

```css
/* Global */
Screen { background: $surface; }
Header { background: $primary; }

/* Dashboard Grid */
#dashboard-grid {
    layout: grid;
    grid-size: 3;
    grid-gutter: 1 2;
    width: 70%;
}

/* Cards */
.dashboard-card {
    border: solid $primary;
    padding: 1 2;
    min-width: 32;
}

/* Coin Toggle Buttons */
.coin-toggle {
    width: 9;
    border: solid $panel;
}
.coin-toggle-active {
    border: solid $primary;
    color: $primary;
    text-style: bold;
}

/* Data Tables */
#whales-table, #woi-table {
    height: 1fr;
    margin: 0 2;
}

/* Chat */
#chat-log {
    height: 1fr;
    border: solid $primary;
}
#chat-input {
    height: 3;
    border: solid $panel;
}

/* Sort Modal */
.sort-modal {
    width: 60%;
    max-width: 80;
    border: solid $primary;
    background: $surface;
}
```

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        APPLICATION STARTUP                          │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  main.py: DashboardApp.on_mount()                                   │
│  ├── Initialize app.whales_full_cache = {}                          │
│  ├── Initialize app.woi_full_cache = {}                             │
│  ├── Start Worker: fetch_whales_full_data() ─┐                      │
│  ├── Start Worker: fetch_woi_full_data() ────┼─ Background threads  │
│  └── Push DashboardScreen({})                │                      │
└─────────────────────────────────────────────────────────────────────┘
                                │
           ┌────────────────────┼────────────────────┐
           │                    │                    │
           ▼                    ▼                    ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ DashboardScreen  │  │ Worker: whales   │  │ Worker: woi      │
│ .on_mount()      │  │ Returns:         │  │ Returns:         │
│ └── Starts own   │  │ {whales_btc:[],  │  │ {users: [...]}   │
│     data fetch   │  │  whales_eth:[],  │  │                  │
│     (frontpage)  │  │  whales_sol:[]}  │  │                  │
└──────────────────┘  └──────────────────┘  └──────────────────┘
           │                    │                    │
           │                    └────────┬───────────┘
           │                             │
           ▼                             ▼
┌──────────────────┐         ┌───────────────────────────────┐
│ _update_display()│         │ on_worker_state_changed()     │
│ Shows "Loading"  │         │ app.whales_full_cache = {...} │
│ then card data   │         │ app.woi_full_cache = {...}    │
└──────────────────┘         └───────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                      USER OPENS DETAIL SCREEN                       │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  User clicks "Open" on Whales card                                  │
│  └── DashboardScreen.on_button_pressed()                            │
│      └── app.push_screen(WhalesScreen(self.data))                   │
│          └── WhalesScreen receives current dashboard data           │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  WhalesScreen.on_mount() [inherits from DataFetchingScreen]         │
│  ├── _update_display()    ← Show data immediately                   │
│  └── _schedule_fetch()                                              │
│      ├── _fetch_data()    ← Immediate fetch                         │
│      └── set_interval(60s, _fetch_data)  ← Periodic refresh         │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Background Worker: _fetch_dashboard_data()                         │
│  └── requests.get(FRONTPAGE_API_URL, timeout=10)                    │
│      └── Returns JSON dict                                          │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  on_worker_state_changed(SUCCESS)                                   │
│  ├── _process_new_data(result)   ← Extract whales data              │
│  └── _update_display()           ← Refresh UI                       │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                    USER OPENS WHALES FULL TABLE                     │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Pressing "w" from Dashboard                                        │
│  └── action_open_whales_full()                                      │
│      └── WhalesFullScreen(self.data, cache=app.whales_full_cache)   │
│          └── Receives cached data, displays immediately             │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  WhalesFullScreen.on_mount()                                        │
│  ├── _update_whale_display()     ← Use cached data                  │
│  └── _fetch_all_whale_data()     ← Start 3 parallel workers         │
│      ├── Worker: BTC_WHALES_API_URL                                 │
│      ├── Worker: ETH_WHALES_API_URL                                 │
│      └── Worker: SOL_WHALES_API_URL                                 │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  on_worker_state_changed() for each coin                            │
│  ├── Store in self.whales_btc/eth/sol                               │
│  ├── _update_whale_display()                                        │
│  └── _update_cache()  ← Sync back to app.whales_full_cache          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Keyboard Bindings Reference

### Global (DashboardApp)

| Key | Action | Description |
|-----|--------|-------------|
| `d` | toggle_dark | Toggle dark/light mode |
| `q` | quit | Quit application |

### Dashboard Screen

| Key | Action | Description |
|-----|--------|-------------|
| `h` / `←` | focus_prev | Focus previous card |
| `l` / `→` | focus_next | Focus next card |
| `k` / `↑` | focus_up | Focus card above |
| `j` / `↓` | focus_down | Focus card below |
| `Enter` | open_focused | Open focused card |
| `w` | open_whales_full | Open Whales Full table |
| `o` | open_woi_full | Open WOI Full table |

### Detail Screens (DataFetchingScreen subclasses)

| Key | Action | Description |
|-----|--------|-------------|
| `b` | go_back | Return to previous screen |

### Whales / Whales Full Screens

| Key | Action | Description |
|-----|--------|-------------|
| `h` / `←` | prev_coin | Select previous coin (BTC→SOL→ETH) |
| `l` / `→` | next_coin | Select next coin (BTC→ETH→SOL) |
| `Tab` | next_coin | Select next coin |
| `Shift+Tab` | prev_coin | Select previous coin |

### Table Screens (Whales Full / WOI Full)

| Key | Action | Description |
|-----|--------|-------------|
| `j` / `↓` | cursor_down | Move cursor down |
| `k` / `↑` | cursor_up | Move cursor up |
| `Ctrl+d` | page_down | Page down |
| `Ctrl+u` | page_up | Page up |
| `g` `g` | cursor_top | Jump to top (vim-style double tap) |
| `G` | cursor_bottom | Jump to bottom |
| `s` | sort_by_column | Open sort modal |
| `S` | toggle_sort_direction | Toggle ASC/DESC |

### Chat Screen

| Key | Action | Description |
|-----|--------|-------------|
| `b` / `Ctrl+b` | go_back | Return to dashboard |
| `Ctrl+l` | clear_chat | Clear chat history |
| `Enter` | submit | Send message |

### Sort Modal

| Key | Action | Description |
|-----|--------|-------------|
| `Escape` / `q` / `b` | cancel | Close without selecting |
| `Enter` | confirm | Apply selection |
| `j` / `↓` | cursor_down | Move selection down |
| `k` / `↑` | cursor_up | Move selection up |
| `S` | toggle_direction | Toggle ASC/DESC |

---

## File Dependency Graph

```
main.py
├── textual.app.App
├── textual.worker.Worker
├── dashboard_screen.DashboardScreen
└── data.fetch_whales_full_data, fetch_woi_full_data

config.py
└── typing.Final

data.py
├── json
├── logging
├── requests
└── config.*

utils.py
├── logging
├── typing.Any
└── config.BAR_WIDTH, PRICE_FORMAT_THRESHOLD, THOUSAND

base_screen.py
├── logging
├── typing.Any, Optional
├── requests
├── textual.screen.Screen
├── textual.worker.Worker
└── config.API_TIMEOUT, FETCH_INTERVAL, FRONTPAGE_API_URL

dashboard_screen.py
├── textual.events
├── textual.app.ComposeResult
├── textual.containers.Container
├── textual.widgets.Button, Footer, Header, Label, Static
├── base_screen.DataFetchingScreen
├── utils.safe_division, safe_float
├── config.MILLION
├── All screen modules (MarketBriefScreen, WhalesScreen, etc.)
└── whales_full.WhalesFullScreen, woi_full.WOIFullScreen

market_brief.py
├── textual.app.ComposeResult
├── textual.containers.Container, HorizontalGroup, VerticalScroll
├── textual.widgets.Digits, Footer, Header, Label
├── base_screen.DataFetchingScreen
└── utils.safe_float

whales.py
├── textual.app.ComposeResult
├── textual.events
├── textual.containers.Container, Horizontal
├── textual.reactive.reactive
├── textual.widgets.Footer, Header, Label, Static
├── base_screen.DataFetchingScreen
├── config.MILLION, THOUSAND
└── utils.format_bar, safe_division, safe_float

whales_full.py
├── logging
├── functools.partial
├── typing.Optional
├── requests
├── textual.events
├── textual.app.ComposeResult
├── textual.containers.Horizontal
├── textual.reactive.reactive
├── textual.screen.Screen  (NOT DataFetchingScreen)
├── textual.widgets.DataTable, Footer, Header, Static
├── textual.worker.Worker
├── config.*
├── sort_modal.SortModal
└── utils.format_price, safe_division, safe_float

woi.py
├── textual.app.ComposeResult
├── textual.containers.Container
├── textual.widgets.Footer, Header, Label
├── base_screen.DataFetchingScreen
├── config.MILLION
└── utils.format_bar, format_time, safe_division

woi_full.py
├── datetime.datetime
├── textual.events
├── textual.app.ComposeResult
├── textual.widgets.DataTable, Footer, Header
├── base_screen.DataFetchingScreen
├── config.THOUSAND, WOI_TRACKED_USERS_API_URL
├── sort_modal.SortModal
└── utils.format_time, safe_division, safe_float

liquidations.py
├── textual.app.ComposeResult
├── textual.containers.Container
├── textual.widgets.Footer, Header, Label
├── base_screen.DataFetchingScreen
├── config.MILLION
└── utils.format_bar, safe_division

polymarket.py
├── textual.app.ComposeResult
├── textual.containers.Container
├── textual.widgets.Footer, Header, Label
├── base_screen.DataFetchingScreen
├── config.MILLION, THOUSAND
└── utils.format_bar, safe_division

arbitrage.py
├── textual.app.ComposeResult
├── textual.containers.Container
├── textual.widgets.Footer, Header, Label
└── base_screen.DataFetchingScreen

chat_screen.py
├── logging
├── typing.Any
├── requests
├── textual.app.ComposeResult
├── textual.containers.Container
├── textual.screen.Screen  (NOT DataFetchingScreen)
├── textual.widgets.Footer, Header, Input, RichLog, Static
├── textual.worker.Worker
└── config.API_TIMEOUT, CHAT_API_URL

sort_modal.py
├── textual.app.ComposeResult
├── textual.containers.Container
├── textual.screen.ModalScreen
└── textual.widgets.Label, ListItem, ListView, Static
```
