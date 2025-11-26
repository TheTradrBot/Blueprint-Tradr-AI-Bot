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
# All available OANDA instruments

# OANDA FX pairs - Majors and Crosses only
FOREX_PAIRS = [
    # Majors
    "EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF",
    "USD_CAD", "AUD_USD", "NZD_USD",

    # EUR crosses
    "EUR_GBP", "EUR_JPY", "EUR_CHF", "EUR_AUD",
    "EUR_CAD", "EUR_NZD",

    # GBP crosses
    "GBP_JPY", "GBP_CHF", "GBP_AUD", "GBP_CAD",
    "GBP_NZD",

    # AUD / NZD / CAD / CHF / JPY crosses
    "AUD_JPY", "AUD_CHF", "AUD_CAD", "AUD_NZD",
    "NZD_JPY", "NZD_CHF", "NZD_CAD",
    "CAD_JPY", "CAD_CHF", "CHF_JPY",
]

# Metals
METALS = [
    "XAU_USD",  # Gold
    "XAG_USD",  # Silver
    "XPT_USD",  # Platinum
    "XPD_USD",  # Palladium
    "XAU_EUR",  # Gold/Euro
    "XAU_GBP",  # Gold/GBP
    "XAU_AUD",  # Gold/AUD
    "XAG_EUR",  # Silver/Euro
    "XCU_USD",  # Copper
]

# Indices
INDICES = [
    "US30_USD",    # Dow Jones
    "SPX500_USD",  # S&P 500
    "NAS100_USD",  # Nasdaq 100
]

# Energies
ENERGIES = [
    "WTICO_USD",   # WTI Crude Oil
    "BCO_USD",     # Brent Crude Oil
    "NATGAS_USD",  # Natural Gas
]

# Crypto
CRYPTO_ASSETS = [
    "BTC_USD",   # Bitcoin
    "ETH_USD",   # Ethereum
    "LTC_USD",   # Litecoin
    "BCH_USD",   # Bitcoin Cash
    "LINK_USD",  # Chainlink
]

# Convenience groups

def all_market_instruments() -> list[str]:
    """All instruments Blueprint can scan."""
    return sorted(set(
        FOREX_PAIRS + METALS + INDICES + ENERGIES + CRYPTO_ASSETS
    ))
