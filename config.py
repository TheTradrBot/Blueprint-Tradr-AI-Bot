# config.py
"""
Configuration for Blueprint Trader AI.

You keep:
- secrets (tokens, API keys) in Replit Secrets (env vars)
- public config (channel IDs, instruments, intervals) here

Account profile settings are now managed via account_profiles.py.
Default: The5ers High Stakes 10K challenge.
Set ACCOUNT_PROFILE env var to switch profiles.
"""

import os

from account_profiles import get_active_profile, ACTIVE_PROFILE


ACTIVE_ACCOUNT_PROFILE = ACTIVE_PROFILE

ACCOUNT_CURRENCY = ACTIVE_PROFILE.currency
ACCOUNT_SIZE = ACTIVE_PROFILE.starting_balance
MAX_DAILY_LOSS_PCT = ACTIVE_PROFILE.max_daily_loss_pct
MAX_TOTAL_LOSS_PCT = ACTIVE_PROFILE.max_total_loss_pct
RISK_PER_TRADE_PCT = ACTIVE_PROFILE.risk_per_trade_pct
MAX_OPEN_RISK_PCT = ACTIVE_PROFILE.max_open_risk_pct
MAX_CONCURRENT_TRADES = ACTIVE_PROFILE.max_concurrent_trades

PHASE_1_TARGET_PCT = ACTIVE_PROFILE.phases[0].profit_target_pct if ACTIVE_PROFILE.phases else 0.08
PHASE_2_TARGET_PCT = ACTIVE_PROFILE.phases[1].profit_target_pct if len(ACTIVE_PROFILE.phases) > 1 else 0.05
MIN_PROFITABLE_DAYS = ACTIVE_PROFILE.phases[0].min_profitable_days if ACTIVE_PROFILE.phases else 3
MIN_PROFIT_PER_DAY_PCT = ACTIVE_PROFILE.phases[0].min_profit_per_day_pct if ACTIVE_PROFILE.phases else 0.005

FRIDAY_CUTOFF_HOUR_UTC = ACTIVE_PROFILE.friday_cutoff_hour_utc
MONDAY_COOLDOWN_HOURS = ACTIVE_PROFILE.monday_cooldown_hours
NEWS_BLACKOUT_MINUTES = ACTIVE_PROFILE.news_blackout_minutes

CONTRACT_SPECS = {
    "USD_JPY": {"pip_value": 0.01, "contract_size": 100000, "pip_location": 2},
    "GBP_USD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
    "EUR_USD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
    "NZD_USD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
    "AUD_USD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
    "USD_CHF": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
    "USD_CAD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
    "EUR_GBP": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
    "EUR_JPY": {"pip_value": 0.01, "contract_size": 100000, "pip_location": 2},
    "GBP_JPY": {"pip_value": 0.01, "contract_size": 100000, "pip_location": 2},
    "AUD_JPY": {"pip_value": 0.01, "contract_size": 100000, "pip_location": 2},
    "XAU_USD": {"pip_value": 0.01, "contract_size": 100, "pip_location": 2},
    "XAG_USD": {"pip_value": 0.001, "contract_size": 5000, "pip_location": 3},
    "NAS100_USD": {"pip_value": 1.0, "contract_size": 1, "pip_location": 0},
    "SPX500_USD": {"pip_value": 1.0, "contract_size": 1, "pip_location": 0},
    "US30_USD": {"pip_value": 1.0, "contract_size": 1, "pip_location": 0},
    "WTICO_USD": {"pip_value": 0.01, "contract_size": 1000, "pip_location": 2},
    "BCO_USD": {"pip_value": 0.01, "contract_size": 1000, "pip_location": 2},
    "BTC_USD": {"pip_value": 1.0, "contract_size": 1, "pip_location": 0},
    "ETH_USD": {"pip_value": 0.01, "contract_size": 1, "pip_location": 2},
}


SIGNAL_MODE = os.getenv("SIGNAL_MODE", "standard")


DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

SCAN_CHANNEL_ID = 1442194985142190230
TRADES_CHANNEL_ID = 1442195008525565962
TRADE_UPDATES_CHANNEL_ID = 1438452127767859254

SCAN_INTERVAL_HOURS = 4


OANDA_API_KEY = os.getenv("OANDA_API_KEY")
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID")
OANDA_API_URL = "https://api-fxpractice.oanda.com"

GRANULARITY_MAP = {
    "M": "M",
    "W": "W",
    "D": "D",
    "H4": "H4",
}


FOREX_PAIRS = [
    "EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF",
    "USD_CAD", "AUD_USD", "NZD_USD",
    "EUR_GBP", "EUR_JPY", "EUR_CHF", "EUR_AUD",
    "EUR_CAD", "EUR_NZD",
    "GBP_JPY", "GBP_CHF", "GBP_AUD", "GBP_CAD",
    "GBP_NZD",
    "AUD_JPY", "AUD_CHF", "AUD_CAD", "AUD_NZD",
    "NZD_JPY", "NZD_CHF", "NZD_CAD",
    "CAD_JPY", "CAD_CHF", "CHF_JPY",
]

METALS = [
    "XAU_USD",
    "XAG_USD",
    "XAU_EUR",
    "XAG_EUR",
]

INDICES = [
    "US30_USD",
    "SPX500_USD",
    "NAS100_USD",
]

ENERGIES = [
    "WTICO_USD",
    "BCO_USD",
]

CRYPTO_ASSETS = [
    "BTC_USD",
    "ETH_USD",
    "LTC_USD",
    "BCH_USD",
]

REMOVED_ASSETS = [
    "NATGAS",
    "XPTUSD", "XPT_USD",
    "XPDUSD", "XPD_USD",
    "XAUGBP", "XAU_GBP",
    "XAUAUD", "XAU_AUD",
    "XCUUSD", "XCU_USD",
]


def validate_asset_not_removed(asset: str) -> bool:
    """
    Validate that an asset is not in the removed list.
    
    These assets have been explicitly removed from live trading and backtests:
    - NATGAS, XPTUSD, XPDUSD, XAUGBP, XAUAUD, XCUUSD
    
    Returns True if asset is valid (not removed), False otherwise.
    """
    normalized = asset.upper().replace("_", "")
    for removed in REMOVED_ASSETS:
        if normalized == removed.replace("_", ""):
            return False
    return True


def all_market_instruments() -> list[str]:
    """All instruments Blueprint can scan."""
    return sorted(set(
        FOREX_PAIRS + METALS + INDICES + ENERGIES + CRYPTO_ASSETS
    ))


def get_profile_info() -> str:
    """Get a display string for current profile."""
    return (
        f"{ACTIVE_PROFILE.display_name} | "
        f"${ACCOUNT_SIZE:,.0f} | "
        f"Risk: {RISK_PER_TRADE_PCT*100:.1f}%/trade | "
        f"Max DD: {MAX_TOTAL_LOSS_PCT*100:.0f}%"
    )
