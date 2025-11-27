# Blueprint Trader AI

## Overview

Blueprint Trader AI is an automated trading signal bot that scans multiple markets (forex, metals, indices, energies, crypto) using a multi-timeframe confluence strategy. The bot identifies high-probability trading opportunities by analyzing 7 technical pillars across monthly, weekly, daily, and 4-hour timeframes. It integrates with Discord for signal delivery and uses OANDA's practice API for market data.

## The5ers High Stakes Account Profiles

The bot now supports configurable account profiles for different prop firm challenges. **Default: The5ers High Stakes 10K**.

### Active Profile: The5ers High Stakes 10K

| Setting | Value |
|---------|-------|
| Starting Balance | $10,000 USD |
| Risk Per Trade | 1% ($100) |
| Max Daily Loss | 5% ($500) |
| Max Total Drawdown | 10% ($1,000) |
| Max Open Risk | 3% ($300) |
| Max Concurrent Trades | 3 |
| Phase 1 Target | 8% (+$800) |
| Phase 2 Target | 5% (+$500) |
| Min Profitable Days | 3 per phase |
| Min Profit/Day | 0.5% ($50) |

### Alternative Profile: The5ers High Stakes 100K

Set `ACCOUNT_PROFILE=the5ers_100k_high_stakes` to switch profiles.

| Setting | Value |
|---------|-------|
| Starting Balance | $100,000 USD |
| Risk Per Trade | 1% ($1,000) |
| Max Daily Loss | 5% ($5,000) |
| Max Total Drawdown | 10% ($10,000) |
| Max Open Risk | 3% ($3,000) |
| Max Concurrent Trades | 5 |

### Trading Time Restrictions

| Rule | Setting |
|------|---------|
| Friday Cutoff | 20:00 UTC (no new trades) |
| Monday Cooldown | 2 hours after open |
| News Blackout | 2 minutes before/after high-impact events |

### Challenge Rules (The5ers High Stakes)

- **Phase 1**: Reach +8% profit with 3+ profitable days (min 0.5%/day)
- **Phase 2**: Reach +5% profit with 3+ profitable days
- **Daily Loss Limit**: 5% of starting balance (with 1% safety buffer = 4%)
- **Total Loss Limit**: 10% of starting balance (with 1% safety buffer = 9%)
- **Unlimited time** to pass each phase

## Recent Changes

**November 27, 2025 - The5ers High Stakes 10K Optimization**

Major refactoring to adapt the bot from a 100K account model to The5ers High Stakes 10K challenge:

### New Modules

1. **account_profiles.py** - Configurable prop firm profiles
   - `THE5ERS_10K_HIGH_STAKES` (default)
   - `THE5ERS_100K_HIGH_STAKES` (alternative)
   - Challenge phases, risk limits, trading restrictions

2. **risk_manager.py** - Risk management system
   - Daily/total loss tracking
   - Projected risk validation before trades
   - Trading time restrictions (Friday, Monday, news)
   - Phase progress tracking
   - Trade validation with detailed rejection reasons

3. **signal_output.py** - MT5 integration readiness
   - MT5-ready signal format
   - Symbol conversion (OANDA to MT5)
   - Signal export to JSON for external execution
   - Risk validation before signal approval

### Updated Modules

- **config.py** - Now uses active profile for all settings
- **position_sizing.py** - Uses profile for account size/risk
- **backtest.py** - Challenge phase simulation with rule checks
- **discord_output.py** - 10K-based metrics, phase progress embeds
- **formatting.py** - 10K profile display
- **main.py** - New /risk, /profile commands; profile info in /debug

### New Discord Commands

- `/profile` - Show current account profile settings
- `/risk` - Show risk status and phase progress

### Backtest Enhancements

- Challenge phase simulation (Phase 1: 8% target)
- Daily loss violation tracking
- Total loss violation tracking
- Profitable days counting
- Pass/fail determination with reasons

**November 26, 2025 - Live Price Fix for Trade Activation**
- Fixed critical bug: Trade entries now use **live OANDA prices** instead of historical candle close prices
- Trade activation is now **gated on live price availability** - no fallback to stale data
- TP/SL monitoring in check_trade_updates now uses live prices instead of H4/D candle closes
- Entry datetime is now properly recorded in TRADE_ENTRY_DATES for accurate timestamps

**November 26, 2025 - Strategy Optimization v2 - Higher Win Rate Focus**

### Performance Summary (Backtest Jan-Dec 2024 - Conservative Exit Logic)
- Total Trades: 121 trades across 4 enabled assets
- Average Win Rate: 63.6%
- Total Return: +74.6%
- Enabled Assets:
  - XAU_USD: 29 trades, 79.3% WR, +27.9% return
  - USD_JPY: 49 trades, 63.3% WR, +28.8% return
  - NZD_USD: 24 trades, 62.5% WR, +10.2% return
  - GBP_USD: 19 trades, 47.4% WR, +7.7% return

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Core Components

1. **Account Profiles** (`account_profiles.py`)
   - Prop firm challenge configurations
   - Risk limits and phase targets
   - Trading time restrictions

2. **Risk Manager** (`risk_manager.py`)
   - Daily/total loss tracking
   - Trade validation
   - Phase progress monitoring

3. **Strategy Engine** (`strategy.py`)
   - 7-pillar confluence evaluation
   - Multi-timeframe analysis (M, W, D, H4)
   - ScanResult dataclass with setup info

4. **Backtest Engine** (`backtest.py`)
   - Walk-forward simulation
   - No look-ahead bias
   - Challenge phase simulation
   - Conservative exit logic

5. **Signal Output** (`signal_output.py`)
   - MT5-ready signal format
   - Risk validation
   - JSON export for external executors

6. **Data Layer** (`data.py`)
   - OANDA v20 API integration
   - Intelligent caching

7. **Cache System** (`cache.py`)
   - TTL-based in-memory cache
   - Thread-safe operations
   - Statistics tracking

8. **Formatting** (`formatting.py`, `discord_output.py`)
   - Discord message formatting
   - Professional embeds
   - Phase progress display

9. **Bot** (`main.py`)
   - Discord slash commands
   - Autoscan loop (4-hour interval)
   - Trade tracking
   - Risk integration

### The 7 Pillars of Confluence

1. **HTF Bias** - Monthly, Weekly, Daily trend alignment
2. **Location** - Price near key S/R levels or supply/demand zones
3. **Fibonacci** - Price in 50%-79.6% retracement zone
4. **Liquidity** - Near equal highs/lows or recent sweeps
5. **Structure** - Market structure supports direction
6. **Confirmation** - 4H BOS, momentum candles, or engulfing patterns
7. **R:R** - Minimum 1.5R to first target

### Trade Status Levels

- **ACTIVE** - Full confirmation, trade entry triggered
- **WATCHING** - Good setup, waiting for confirmation
- **SCAN** - Low confluence, no actionable setup

## Discord Commands

**Scanning:**
- `/scan [asset]` - Detailed analysis of a single asset
- `/forex` - Scan all forex pairs
- `/crypto` - Scan crypto assets
- `/com` - Scan commodities (metals + energies)
- `/indices` - Scan stock indices
- `/market` - Full market scan

**Trading:**
- `/trade` - Show active trades with status
- `/live` - Latest prices for all assets

**Risk & Profile:**
- `/risk` - Show risk status and phase progress
- `/profile` - Show account profile settings

**Analysis:**
- `/backtest [asset] [period]` - Test strategy performance

**System:**
- `/cache` - View cache statistics
- `/clearcache` - Clear data cache
- `/cleartrades` - Clear active trade tracking
- `/debug` - Bot health and status
- `/help` - Show all commands

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DISCORD_BOT_TOKEN` | Discord bot token (required) |
| `OANDA_API_KEY` | OANDA API key (required for data) |
| `OANDA_ACCOUNT_ID` | OANDA account ID |
| `ACCOUNT_PROFILE` | Profile name (default: `the5ers_10k_high_stakes`) |
| `SIGNAL_MODE` | `standard` (default) or `aggressive` |

## MT5 Integration Preparation

The bot is structured for future MT5 executor integration:

### Signal Format (`signal_output.py`)

```python
MT5Signal(
    signal_id="ABC12345",
    symbol_mt5="EURUSD",  # MT5 format
    direction="BUY",
    order_type="MARKET",
    entry_price=1.08500,
    stop_loss=1.08200,
    take_profit_1=1.08800,
    lot_size=0.05,
    risk_usd=100.00,
    risk_pct=0.01,
    valid=True,
    status="approved",
)
```

### Integration Points

1. **Signal Generation**: `create_signal_from_scan(scan_result)`
2. **Risk Validation**: Signals are validated against risk manager
3. **JSON Export**: `export_signals_to_file(signals, "signals.json")`
4. **MT5 Parameters**: `signal.to_mt5_order_params()` returns dict for `mt5.order_send()`

### Future: MT5 Executor (Windows VPS)

```python
import MetaTrader5 as mt5
from signal_output import MT5Signal

# Load signals from file
with open("signals.json") as f:
    data = json.load(f)

# Execute approved signals
for sig_data in data["signals"]:
    if sig_data["valid"] and sig_data["status"] == "approved":
        result = mt5.order_send(MT5Signal(**sig_data).to_mt5_order_params())
```

## Python Dependencies

- `discord-py>=2.6.4` - Discord bot framework (async)
- `pandas>=2.3.3` - Data processing
- `requests>=2.32.5` - HTTP client for OANDA API

### Dependency Management
- **Managed via**: `pyproject.toml` + `uv.lock`
- Run `uv sync` to install exact locked versions
- Do NOT ignore `uv.lock` - it ensures consistent versions

## 24/7 Hosting Options

### Option 1: Replit Deployments (Recommended)

1. **Autoscale Deployment** - Click "Deploy" in Replit
   - Select "Autoscale" deployment type
   - Set run command: `python main.py`
   - Bot runs continuously with automatic restarts
   - Cost: Based on compute usage (~$5-20/month)

2. **Reserved VM Deployment** - For guaranteed uptime
   - Select "Reserved VM" deployment
   - Bot has dedicated resources
   - Cost: Starting at $7/month

### Option 2: VPS Server

For MT5 integration (requires Windows):

1. Get Windows VPS with MT5 installed
2. Run this bot + MT5 executor side by side
3. Bot generates signals, executor places trades

### Keeping Secrets Safe

- **Never commit secrets to Git**
- Use environment variables or secrets managers
- On Replit: Use the Secrets tab
- On VPS: Use `.env` files (add to .gitignore)
- Rotate API keys periodically
