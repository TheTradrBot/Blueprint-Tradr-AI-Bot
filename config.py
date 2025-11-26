# config.py
"""
Configuration for Blueprint Trader AI.

You keep:
- secrets (tokens, API keys) in Replit Secrets (env vars)
- public config (channel IDs, instruments, intervals) here
"""

import os


# ==== 5%ers 100K High Stakes Risk Model ====

ACCOUNT_CURRENCY = "USD"
ACCOUNT_SIZE = 100_000
MAX_DAILY_LOSS_PCT = 0.05
MAX_TOTAL_LOSS_PCT = 0.10
RISK_PER_TRADE_PCT = 0.01
MAX_OPEN_RISK_PCT = 0.03
MIN_WITHDRAWAL_USD = 150

CONTRACT_SPECS = {
    "USD_JPY": {"pip_value": 0.01, "contract_size": 100000, "pip_location": 2},
    "GBP_USD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
    "EUR_USD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
    "NZD_USD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
    "AUD_USD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
    "USD_CHF": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
    "USD_CAD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
    "XAU_USD": {"pip_value": 0.01, "contract_size": 100, "pip_location": 2},
    "XAG_USD": {"pip_value": 0.001, "contract_size": 5000, "pip_location": 3},
    "NAS100_USD": {"pip_value": 1.0, "contract_size": 1, "pip_location": 0},
    "SPX500_USD": {"pip_value": 1.0, "contract_size": 1, "pip_location": 0},
    "WTICO_USD": {"pip_value": 0.01, "contract_size": 1000, "pip_location": 2},
    "BCO_USD": {"pip_value": 0.01, "contract_size": 1000, "pip_location": 2},
    "BTC_USD": {"pip_value": 1.0, "contract_size": 1, "pip_location": 0},
    "ETH_USD": {"pip_value": 0.01, "contract_size": 1, "pip_location": 2},
}


# How strict the confluence engine is.
# "standard"  = balanced trades and quality (recommended for live trading)
# "aggressive" = more trades, looser filters (for experimentation/backtesting)
# Set SIGNAL_MODE environment variable to override, e.g., SIGNAL_MODE=aggressive
SIGNAL_MODE = os.getenv("SIGNAL_MODE", "standard")


# ==== Discord ====

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Replace these with your actual channel IDs (integers)
SCAN_CHANNEL_ID = 1442194985142190230        # <- scan channel ID
TRADES_CHANNEL_ID = 1442195008525565962      # <- trades channel ID
TRADE_UPDATES_CHANNEL_ID = 1438452127767859254  # <- trade updates channel ID

# Autoscan interval (hours)
SCAN_INTERVAL_HOURS = 4  # every 4H as per your spec


# ==== Data source: OANDA (practice) ====

OANDA_API_KEY = os.getenv("OANDA_API_KEY")          # set in Replit secrets
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID")    # set in Replit secrets
OANDA_API_URL = "https://api-fxpractice.oanda.com"  # practice endpoint

# Granularity mapping for OANDA
GRANULARITY_MAP = {
    "M": "M",      # Monthly
    "W": "W",      # Weekly
    "D": "D",      # Daily
    "H4": "H4",    # 4-hour
}


# ==== Instruments & groups ====
# These are example sets. You can expand them later.

# OANDA FX pairs - Optimized for best performers based on backtest
# Pairs meeting 60%+ win rate in Jan-Dec 2024 backtest:
# - USD_JPY: 71.2% WR, 59 trades
# - NZD_USD: 70.0% WR, 30 trades  
# - GBP_USD: 52.4% WR, 21 trades (borderline)
# Excluded due to low win rate: EUR_USD, AUD_USD, USD_CHF, USD_CAD
FOREX_PAIRS = [
    "USD_JPY",
    "GBP_USD",
    "NZD_USD",
    # Add more pairs after validating via /backtest command
]

# Metals (subset of commodities)
METALS = [
    "XAU_USD",  # Gold
    "XAG_USD",  # Silver
]

# Indices
INDICES = [
    "NAS100_USD",  # Nasdaq
    "SPX500_USD",  # S&P 500
]

# Energies
ENERGIES = [
    "WTICO_USD",   # WTI Crude
    "BCO_USD",     # Brent
]

# Crypto
CRYPTO_ASSETS = [
    "BTC_USD",
    "ETH_USD",
]

# Convenience groups

def all_market_instruments() -> list[str]:
    """All instruments Blueprint can scan."""
    return sorted(set(
        FOREX_PAIRS + METALS + INDICES + ENERGIES + CRYPTO_ASSETS
    ))
