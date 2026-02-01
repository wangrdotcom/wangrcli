<p align="center">
  <pre>
██╗    ██╗ █████╗ ███╗   ██╗ ██████╗ ██████╗
██║    ██║██╔══██╗████╗  ██║██╔════╝ ██╔══██╗
██║ █╗ ██║███████║██╔██╗ ██║██║  ███╗██████╔╝
██║███╗██║██╔══██║██║╚██╗██║██║   ██║██╔══██╗
╚███╔███╔╝██║  ██║██║ ╚████║╚██████╔╝██║  ██║
 ╚══╝╚══╝ ╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═╝
  </pre>
  <strong>Terminal-native crypto market dashboard</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/wangr/"><img src="https://img.shields.io/pypi/v/wangr?color=blue&label=PyPI" alt="PyPI"></a>
  <a href="https://pypi.org/project/wangr/"><img src="https://img.shields.io/pypi/pyversions/wangr?color=blue" alt="Python"></a>
  <a href="https://github.com/oliursahin/wangrcli/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-green.svg" alt="License"></a>
</p>

<p align="center">
  Real-time whale tracking • Liquidation monitoring • Cross-exchange arbitrage • AI-powered analysis
</p>

---

## Features

| Feature | Description |
|---------|-------------|
| **Market Brief** | Live BTC, ETH, SOL prices with 24h change sparklines |
| **Whale Tracker** | Monitor whale positions on Hyperliquid — longs vs shorts, position sizes |
| **Wallets of Interest** | Track smart money: PnL, win rates, trade history |
| **Liquidations** | Real-time liquidation feed with exchange breakdown |
| **Polymarket** | Whale activity on prediction markets |
| **Arbitrage Scanner** | Cross-exchange opportunities — Futures, Spot, and DEX |
| **AI Chat** | Ask questions about whales, markets, and positions |

---

## Install

```bash
pip install wangr
```

## Run

```bash
wangr
```

That's it. No config needed.

---

## Keyboard Shortcuts

### Navigation
| Key | Action |
|-----|--------|
| `h` `j` `k` `l` | Vim-style navigation |
| `←` `↓` `↑` `→` | Arrow key navigation |
| `Enter` | Open selected card |
| `b` | Go back |
| `q` | Quit |

### Tables
| Key | Action |
|-----|--------|
| `s` | Sort by column |
| `S` | Toggle sort direction |
| `Ctrl+D` | Page down |
| `Ctrl+U` | Page up |
| `G` | Jump to bottom |

### Views
| Key | Action |
|-----|--------|
| `f` | Toggle market type (Arbitrage) |
| `←` `→` | Switch between tabs |
| `s` | Open settings |

---

## Dashboard Cards

```
┌─────────────────────┬─────────────────────┬─────────────────────┐
│   📊 Market Brief   │     🐋 Whales       │  🔍 Wallets of Int  │
│                     │                     │                     │
│  ₿ $97,234  ▲+2.4%  │  ₿ 127  ████░░ 89L  │  PnL    $12.4M      │
│  Ξ  $3,412  ▲+1.2%  │  Ξ  43  ███░░░ 28L  │  Win    ████░  72%  │
│  ◎    $198  ▼-0.8%  │  ◎  31  ██░░░░ 18L  │  Trades 1,247       │
│                     │                     │                     │
│       [Open]        │       [Open]        │       [Open]        │
├─────────────────────┼─────────────────────┼─────────────────────┤
│   💧 Liquidations   │   📈 Polymarket     │   📉 Arbitrage      │
│                     │                     │                     │
│  24h  $142.3M       │  Traders  12,847    │  ✓ Spot    +0.12%   │
│  ↑    ████░  $89M   │  PnL      $2.1M     │  ✓ Futures +0.08%   │
│  ↓    ██░░░  $53M   │  Volume   $847K     │  • DEX     -0.02%   │
│                     │                     │                     │
│       [Open]        │       [Open]        │       [Open]        │
└─────────────────────┴─────────────────────┴─────────────────────┘
```

---

## Screens

### Whale Tracker
Track large positions across BTC, ETH, and SOL on Hyperliquid:
- Position count and breakdown (longs vs shorts)
- Real-time updates
- Sortable columns

### Arbitrage Scanner
Find cross-exchange price discrepancies:
- **Futures** — Funding rate differentials, net spread after funding
- **Spot** — Direct price arbitrage between CEXs
- **DEX** — On-chain arbitrage opportunities

### Liquidations
Monitor market liquidations in real-time:
- 24h totals with long/short breakdown
- Per-exchange statistics
- Largest liquidations (24h and all-time)

### AI Chat
Built-in AI assistant for market analysis:
- Query whale positions
- Get market summaries
- Analyze wallet activity

---

## Requirements

- Python 3.11+
- Terminal with Unicode support
- (Optional) OpenAI API key for AI features

---

## Configuration

Press `s` from the dashboard to open Settings.

For AI features (Chat and Polymarket Agent), you'll need to configure an API key.

---

## Built With

- [Textual](https://textual.textualize.io/) — Modern TUI framework
- [Hyperliquid API](https://hyperliquid.xyz/) — Market data
- [OpenAI Agents](https://platform.openai.com/) — AI capabilities

---

## License

Apache 2.0 — See [LICENSE](LICENSE) for details.
