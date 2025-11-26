# Blueprint Trader AI

## Overview

Blueprint Trader AI is an automated trading signal bot that scans multiple markets (forex, metals, indices, energies, crypto) using a multi-timeframe confluence strategy. The bot identifies high-probability trading opportunities by analyzing 7 technical pillars across monthly, weekly, daily, and 4-hour timeframes. It integrates with Discord for signal delivery and uses OANDA's practice API for market data.

## Recent Changes

**November 26, 2024 - Major Strategy Optimization & System Upgrade**

### Strategy Improvements
- Optimized confluence detection with more flexible thresholds
- Improved Fibonacci retracement calculations (50%-79.6% zones)
- Enhanced liquidity detection with sweep lookback up to 8 candles
- Better swing detection with asymmetric lookback periods
- Tighter stop loss placement using ATR-based calculations
- Realistic R:R targets (1.5R, 2.5R, 4R, 5.5R, 7R)

### Backtest Improvements
- No look-ahead bias - uses only data available at each evaluation point
- Conservative exit assumptions (SL hit first when both SL/TP touched)
- 3-bar cooldown between trades to avoid overtrading
- Detailed trade logging with TP/SL breakdown

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
- **Discord API** - Bot communication (py-cord library)
- **OANDA v20 API** - Market data (practice endpoint)

### Environment Variables
- `DISCORD_BOT_TOKEN` - Discord bot token
- `OANDA_API_KEY` - OANDA API key
- `OANDA_ACCOUNT_ID` - OANDA account ID

### Python Dependencies
- `py-cord>=2.6.1` - Discord bot framework
- `requests>=2.32.5` - HTTP client for OANDA API

## Configuration

Key settings in `config.py`:
- `SIGNAL_MODE` - "standard" (stricter) or "aggressive" (more signals)
- `SCAN_INTERVAL_HOURS` - Autoscan frequency (default: 4)
- Discord channel IDs for scan, trades, and updates
- Instrument lists for each market type