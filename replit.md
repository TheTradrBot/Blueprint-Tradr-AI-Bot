# Blueprint Trader AI

## Overview

Blueprint Trader AI is an automated trading signal bot that scans multiple markets (forex, metals, indices, energies, crypto) using a multi-timeframe confluence strategy. The bot identifies high-probability trading opportunities by analyzing 7 technical pillars across monthly, weekly, daily, and 4-hour timeframes. It integrates with Discord for signal delivery and uses OANDA's practice API for market data.

## 5%ers 100K High Stakes Risk Model

The bot is configured for The 5%ers 100K High Stakes account with the following risk settings:

### Account Configuration
- **Account Size:** $100,000 USD
- **Risk Per Trade:** 1% ($1,000)
- **Max Daily Loss:** 5% ($5,000)
- **Max Total Drawdown:** 10% ($10,000)
- **Max Open Risk:** 3% ($3,000)

### Position Sizing
The bot calculates lot sizes based on:
1. Account size and risk percentage
2. Stop loss distance in pips
3. Pip value per lot for each instrument

Example: For a 40-pip stop on EUR/USD with 1% risk:
- Risk USD = $100,000 × 1% = $1,000
- Pip value per lot = $10
- Lot size = $1,000 ÷ (40 × $10) = 2.50 lots

### Discord Outputs
Trade signals include:
- **Entry & Levels** - Entry, SL, TP1/TP2/TP3 with R:R values
- **Risk & Lot Size** - Account size, risk %, USD risk, lot size
- **Confluence** - Technical factors aligned for the trade

### Key Files
- `config.py` - Risk configuration (ACCOUNT_SIZE, RISK_PER_TRADE_PCT, etc.)
- `position_sizing.py` - Lot size calculation functions
- `discord_output.py` - Professional Discord embed formatting

## Recent Changes

**November 26, 2025 - 5%ers Risk Model & Discord Embeds**
- Added 5%ers 100K High Stakes account risk configuration
- Implemented position sizing with lot size calculations
- Professional Discord embeds for trade setups and updates
- Backtest now shows total profit in $ and % with 5%ers model
- Added max drawdown tracking to backtest results

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
- Disabled Assets (need pair-specific tuning): EUR_USD, AUD_USD, USD_CHF, USD_CAD

**Note:** Exit logic is fully conservative - TP2/TP3 only credited after TP1 hit on previous bar. This produces realistic results suitable for live trading expectations.

### Key Optimizations (v2)
1. **Trailing Stop System** - After TP1 hit, SL moves to breakeven (entry price)
2. **Conservative Exit Logic** - SL checked first when both SL and TP hit same bar
3. **Same-bar TP1 Validation** - After TP1, immediately checks if trailing stop also hit
4. **Wider Stop Losses** - ATR multiplier increased to 1.5x for better protection
5. **Tighter Take Profits** - TP1 at 0.6R, TP2 at 1.1R for higher hit rates
6. **Extended Fibonacci Zones** - 38.2% to 88.6% retracement window
7. **Better Liquidity Detection** - Increased lookback to 12 candles, 80-bar history

### Strategy Changes
- Reduced confluence threshold from 3 to 2 for more trade opportunities
- Simplified activation: confluence >= 2 and quality_factors >= 1
- SL-first priority in exit logic for conservative backtest results
- Structure-based stop loss with swing point detection

### Backtest Improvements
- Trailing stop logic protects profits after TP1
- TP1+Trail exit category for trades that hit TP1 then trail out
- Win rate calculation includes all profitable exits

### Performance & Caching
- Added intelligent caching layer (`cache.py`) for OANDA API responses
- TTL-based caching: Monthly (1hr), Weekly (30min), Daily (10min), H4 (5min)
- Cache statistics and management commands (/cache, /clearcache)

### Discord UX Improvements
- Cleaner autoscan output with active/watching counts
- Detailed single asset scans with setup type and "what to look for"
- Better formatting with emojis for direction (🟢/🔴)
- Improved help command with all available commands

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Core Components

1. **Strategy Engine** (`strategy.py`)
   - 7-pillar confluence evaluation
   - Multi-timeframe analysis (M, W, D, H4)
   - ScanResult dataclass with setup info

2. **Backtest Engine** (`backtest.py`)
   - Walk-forward simulation
   - No look-ahead bias
   - Conservative exit logic

3. **Data Layer** (`data.py`)
   - OANDA v20 API integration
   - Intelligent caching

4. **Cache System** (`cache.py`)
   - TTL-based in-memory cache
   - Thread-safe operations
   - Statistics tracking

5. **Formatting** (`formatting.py`)
   - Discord message formatting
   - Scan summaries and details
   - Backtest result formatting

6. **Bot** (`main.py`)
   - Discord slash commands
   - Autoscan loop (4-hour interval)
   - Trade tracking

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

**Analysis:**
- `/backtest [asset] [period]` - Test strategy performance

**System:**
- `/cache` - View cache statistics
- `/clearcache` - Clear data cache
- `/help` - Show all commands

## External Dependencies

### Services
- **Discord API** - Bot communication (discord.py library)
- **OANDA v20 API** - Market data (practice endpoint)

### Environment Variables
- `DISCORD_BOT_TOKEN` - Discord bot token
- `OANDA_API_KEY` - OANDA API key (optional - enables autoscan)
- `OANDA_ACCOUNT_ID` - OANDA account ID

### Python Dependencies
- `discord-py>=2.6.4` - Discord bot framework (async)
- `pandas>=2.3.3` - Data processing
- `requests>=2.32.5` - HTTP client for OANDA API

### Dependency Management
- **Managed via**: `pyproject.toml` + `uv.lock`
- **Important**: `uv.lock` is committed to Git - it ensures consistent dependency versions across all clones
- When you clone from GitHub, run `uv sync` to install exact locked versions
- Do NOT ignore `uv.lock` - it prevents package version mismatches

## Configuration

Key settings in `config.py`:
- `SIGNAL_MODE` - "standard" (stricter) or "aggressive" (more signals)
- `SCAN_INTERVAL_HOURS` - Autoscan frequency (default: 4)
- Discord channel IDs for scan, trades, and updates
- Instrument lists for each market type

## Optimization System

The bot includes a comprehensive strategy optimization framework for backtesting and tuning.

### New Modules

1. **data_loader.py** - CSV data loading for historical backtesting
   - Load OHLCV data from CSV files
   - Year-by-year filtering
   - Timeframe conversion utilities

2. **strategy_core.py** - Parameterized strategy engine
   - `StrategyParams` dataclass for all tunable parameters
   - `generate_signals()` - Generate signals from historical data
   - `simulate_trades()` - Walk-forward trade simulation
   - Same logic used by both backtests and live scanning

3. **backtest_engine.py** - Enhanced backtest framework
   - Comprehensive performance metrics
   - No look-ahead bias (walk-forward)
   - Year-by-year analysis
   - Results export to CSV

4. **optimizer.py** - Strategy parameter optimization
   - Grid/random search over parameter space
   - Multi-objective scoring
   - Configuration saving/loading

5. **report.py** - Performance reporting
   - Asset-by-asset analysis
   - Baseline vs optimized comparison
   - Target achievement tracking

6. **settings.py** - Configuration management
   - Toggle between baseline and optimized modes
   - Per-asset parameter overrides

### Optimization Targets

Historical optimization aims for:
- >= 50 trades per year
- 70-100% win rate
- >= 50% yearly return

### CLI Commands

```bash
# Run baseline backtests
python backtest_engine.py --mode baseline

# Run optimization
python optimizer.py --max-configs 50

# Generate performance report
python report.py

# Compare baseline vs optimized
python report.py --compare

# Quick single-asset backtest
python backtest_engine.py --asset XAU_USD --year 2024
```

### Data Setup

Place CSV files in the `/data` folder:
- Naming: `EURUSD.csv`, `XAUUSD.csv`, etc.
- Required columns: timestamp, open, high, low, close, volume
- Timestamp format: ISO 8601 (e.g., 2024-01-15)

### Strategy Toggle

Set environment variable to switch modes:
- `USE_OPTIMIZED_STRATEGY=true` - Use optimized parameters (default)
- `USE_OPTIMIZED_STRATEGY=false` - Use baseline parameters

Optimized configuration is stored in `best_strategy_config.json`.