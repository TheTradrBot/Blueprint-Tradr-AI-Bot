"""
Account Profiles for Blueprint Trader AI.

Defines prop firm challenge configurations including:
- The5ers High Stakes 10K (default)
- The5ers High Stakes 100K (alternative)

Each profile contains all parameters needed for:
- Risk management
- Position sizing
- Challenge phase tracking
- Backtest simulation
"""

from dataclasses import dataclass, field
from typing import Optional
import os


@dataclass
class ChallengePhase:
    """Single phase of a prop firm challenge."""
    name: str
    profit_target_pct: float
    min_profitable_days: int
    min_profit_per_day_pct: float


@dataclass
class AccountProfile:
    """Complete account profile for prop firm trading."""
    name: str
    display_name: str
    starting_balance: float
    currency: str
    
    max_daily_loss_pct: float
    max_total_loss_pct: float
    
    risk_per_trade_pct: float
    max_open_risk_pct: float
    max_concurrent_trades: int
    
    phases: list = field(default_factory=list)
    
    daily_loss_buffer_pct: float = 0.01
    total_loss_buffer_pct: float = 0.01
    
    friday_cutoff_hour_utc: int = 20
    monday_cooldown_hours: int = 2
    
    allow_weekend_holding: bool = True
    allow_overnight_holding: bool = True
    news_blackout_minutes: int = 2
    
    platform: str = "MT5"
    hedge_mode: bool = True
    
    def get_safe_daily_loss_limit(self) -> float:
        """Daily loss limit with safety buffer."""
        return self.max_daily_loss_pct - self.daily_loss_buffer_pct
    
    def get_safe_total_loss_limit(self) -> float:
        """Total loss limit with safety buffer."""
        return self.max_total_loss_pct - self.total_loss_buffer_pct
    
    def get_phase(self, phase_num: int) -> Optional[ChallengePhase]:
        """Get phase by number (1-indexed)."""
        if 0 < phase_num <= len(self.phases):
            return self.phases[phase_num - 1]
        return None
    
    def get_max_risk_per_trade_usd(self) -> float:
        """Maximum risk in USD per trade."""
        return self.starting_balance * self.risk_per_trade_pct
    
    def get_max_open_risk_usd(self) -> float:
        """Maximum total open risk in USD."""
        return self.starting_balance * self.max_open_risk_pct
    
    def get_daily_loss_limit_usd(self) -> float:
        """Daily loss limit in USD."""
        return self.starting_balance * self.max_daily_loss_pct
    
    def get_total_loss_limit_usd(self) -> float:
        """Total loss limit in USD (max drawdown)."""
        return self.starting_balance * self.max_total_loss_pct


THE5ERS_10K_HIGH_STAKES = AccountProfile(
    name="the5ers_10k_high_stakes",
    display_name="The5ers High Stakes 10K",
    starting_balance=10_000,
    currency="USD",
    
    max_daily_loss_pct=0.05,
    max_total_loss_pct=0.10,
    
    risk_per_trade_pct=0.01,
    max_open_risk_pct=0.03,
    max_concurrent_trades=3,
    
    phases=[
        ChallengePhase(
            name="Phase 1",
            profit_target_pct=0.08,
            min_profitable_days=3,
            min_profit_per_day_pct=0.005,
        ),
        ChallengePhase(
            name="Phase 2",
            profit_target_pct=0.05,
            min_profitable_days=3,
            min_profit_per_day_pct=0.005,
        ),
    ],
    
    daily_loss_buffer_pct=0.01,
    total_loss_buffer_pct=0.01,
    
    friday_cutoff_hour_utc=20,
    monday_cooldown_hours=2,
    
    allow_weekend_holding=True,
    allow_overnight_holding=True,
    news_blackout_minutes=2,
    
    platform="MT5",
    hedge_mode=True,
)


THE5ERS_100K_HIGH_STAKES = AccountProfile(
    name="the5ers_100k_high_stakes",
    display_name="The5ers High Stakes 100K",
    starting_balance=100_000,
    currency="USD",
    
    max_daily_loss_pct=0.05,
    max_total_loss_pct=0.10,
    
    risk_per_trade_pct=0.01,
    max_open_risk_pct=0.03,
    max_concurrent_trades=5,
    
    phases=[
        ChallengePhase(
            name="Phase 1",
            profit_target_pct=0.08,
            min_profitable_days=3,
            min_profit_per_day_pct=0.005,
        ),
        ChallengePhase(
            name="Phase 2",
            profit_target_pct=0.05,
            min_profitable_days=3,
            min_profit_per_day_pct=0.005,
        ),
    ],
    
    daily_loss_buffer_pct=0.01,
    total_loss_buffer_pct=0.01,
    
    friday_cutoff_hour_utc=20,
    monday_cooldown_hours=2,
    
    allow_weekend_holding=True,
    allow_overnight_holding=True,
    news_blackout_minutes=2,
    
    platform="MT5",
    hedge_mode=True,
)


AVAILABLE_PROFILES = {
    "the5ers_10k_high_stakes": THE5ERS_10K_HIGH_STAKES,
    "the5ers_100k_high_stakes": THE5ERS_100K_HIGH_STAKES,
}


def get_active_profile() -> AccountProfile:
    """
    Get the currently active account profile.
    
    Set ACCOUNT_PROFILE env var to switch profiles:
    - "the5ers_10k_high_stakes" (default)
    - "the5ers_100k_high_stakes"
    """
    profile_name = os.getenv("ACCOUNT_PROFILE", "the5ers_10k_high_stakes")
    return AVAILABLE_PROFILES.get(profile_name, THE5ERS_10K_HIGH_STAKES)


def list_profiles() -> list:
    """List all available profile names."""
    return list(AVAILABLE_PROFILES.keys())


ACTIVE_PROFILE = get_active_profile()
