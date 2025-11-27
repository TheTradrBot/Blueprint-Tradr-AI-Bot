"""
Challenge Simulator for Blueprint Trader AI.

Simulates The5ers High Stakes 10K challenge for a given month/year.
Runs backtests with proper risk management rules to determine if
Phase 1 (+8%) and Phase 2 (+5%) would be passed.

Features:
- Month/year challenge simulation
- Daily/total drawdown tracking per The5ers rules
- Phase progression tracking
- Detailed reporting of pass/fail results
"""

from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
import calendar

from data import get_ohlcv
from config import (
    FOREX_PAIRS,
    METALS,
    INDICES,
    ENERGIES,
    CRYPTO_ASSETS,
    ACCOUNT_SIZE,
    RISK_PER_TRADE_PCT,
)
from account_profiles import AccountProfile, get_active_profile
from backtest import run_backtest


@dataclass
class ChallengeResult:
    """Results from a challenge simulation."""
    year: int
    month: int
    
    phase1_passed: bool = False
    phase2_passed: bool = False
    both_passed: bool = False
    
    days_to_pass: int = 0
    total_profit_pct: float = 0.0
    total_profit_usd: float = 0.0
    total_trades: int = 0
    
    max_daily_drawdown_pct: float = 0.0
    max_total_drawdown_pct: float = 0.0
    
    daily_loss_violations: int = 0
    total_loss_violations: int = 0
    
    trading_days: int = 0
    profitable_days: int = 0
    
    failure_reason: str = ""
    
    phase1_profit_pct: float = 0.0
    phase1_days: int = 0
    phase2_profit_pct: float = 0.0
    phase2_days: int = 0
    
    trades: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for reporting."""
        return {
            "year": self.year,
            "month": self.month,
            "phase1_passed": self.phase1_passed,
            "phase2_passed": self.phase2_passed,
            "both_passed": self.both_passed,
            "days_to_pass": self.days_to_pass,
            "total_profit_pct": self.total_profit_pct,
            "total_profit_usd": self.total_profit_usd,
            "total_trades": self.total_trades,
            "max_daily_drawdown_pct": self.max_daily_drawdown_pct,
            "max_total_drawdown_pct": self.max_total_drawdown_pct,
            "daily_loss_violations": self.daily_loss_violations,
            "total_loss_violations": self.total_loss_violations,
            "trading_days": self.trading_days,
            "profitable_days": self.profitable_days,
            "failure_reason": self.failure_reason,
            "phase1_profit_pct": self.phase1_profit_pct,
            "phase1_days": self.phase1_days,
            "phase2_profit_pct": self.phase2_profit_pct,
            "phase2_days": self.phase2_days,
        }


def get_all_tradeable_assets() -> List[str]:
    """Get all tradeable assets."""
    return sorted(set(
        FOREX_PAIRS + METALS + INDICES + ENERGIES + CRYPTO_ASSETS
    ))


def simulate_challenge_for_month(
    year: int,
    month: int,
    profile: Optional[AccountProfile] = None,
    assets: Optional[List[str]] = None,
) -> ChallengeResult:
    """
    Simulate a The5ers challenge for a specific month/year.
    
    Uses the unified strategy logic from backtest.py to simulate trades,
    then applies challenge rules to determine if phases would be passed.
    
    Args:
        year: Calendar year (e.g., 2024)
        month: Calendar month (1-12)
        profile: Account profile to use (defaults to active profile)
        assets: Assets to trade (defaults to all tradeable assets)
    
    Returns:
        ChallengeResult with detailed simulation results
    """
    if profile is None:
        profile = get_active_profile()
    
    if assets is None:
        assets = get_all_tradeable_assets()
    
    result = ChallengeResult(year=year, month=month)
    
    _, last_day = calendar.monthrange(year, month)
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)
    period_str = f"{start_date.strftime('%d %b %Y')} - {end_date.strftime('%d %b %Y')}"
    
    all_trades: List[Dict] = []
    
    print(f"\n[Challenge Simulator] Running simulation for {calendar.month_name[month]} {year}")
    print(f"[Challenge Simulator] Assets: {len(assets)}, Period: {period_str}")
    print(f"[Challenge Simulator] Profile: {profile.display_name}")
    
    for asset in assets:
        try:
            bt_result = run_backtest(asset, period_str)
            if bt_result.get("trades"):
                for trade in bt_result["trades"]:
                    trade["asset"] = asset
                    all_trades.append(trade)
        except Exception as e:
            print(f"[Challenge Simulator] Error backtesting {asset}: {e}")
            continue
    
    if not all_trades:
        result.failure_reason = "No trades generated during this period"
        return result
    
    all_trades.sort(key=lambda t: t.get("exit_date", t.get("entry_date", "")))
    
    result.total_trades = len(all_trades)
    result.trades = all_trades
    
    account_size = profile.starting_balance
    risk_per_trade_pct = profile.risk_per_trade_pct
    risk_per_trade_usd = account_size * risk_per_trade_pct
    
    phase1_target = profile.phases[0].profit_target_pct if profile.phases else 0.08
    phase2_target = profile.phases[1].profit_target_pct if len(profile.phases) > 1 else 0.05
    max_daily_loss = profile.max_daily_loss_pct
    max_total_loss = profile.max_total_loss_pct
    min_profitable_days = profile.phases[0].min_profitable_days if profile.phases else 3
    min_profit_per_day = profile.phases[0].min_profit_per_day_pct if profile.phases else 0.005
    
    balance = account_size
    peak_balance = account_size
    phase1_start_balance = account_size
    
    daily_pnl: Dict[str, float] = {}
    current_phase = 1
    phase1_complete_day = 0
    phase2_complete_day = 0
    
    trading_day_count = 0
    
    for trade in all_trades:
        trade_date = trade.get("exit_date", trade.get("entry_date", ""))
        rr = trade.get("rr", 0)
        pnl_usd = rr * risk_per_trade_usd
        
        if trade_date not in daily_pnl:
            daily_pnl[trade_date] = 0.0
            trading_day_count += 1
        daily_pnl[trade_date] += pnl_usd
        
        balance += pnl_usd
        
        if balance > peak_balance:
            peak_balance = balance
        
        day_loss = daily_pnl[trade_date]
        if day_loss < 0 and abs(day_loss) > account_size * max_daily_loss:
            result.daily_loss_violations += 1
        
        total_dd = account_size - balance
        if total_dd > account_size * max_total_loss:
            result.total_loss_violations += 1
        
        daily_dd_pct = abs(day_loss) / account_size * 100 if day_loss < 0 else 0
        if daily_dd_pct > result.max_daily_drawdown_pct:
            result.max_daily_drawdown_pct = daily_dd_pct
        
        total_dd_pct = total_dd / account_size * 100 if total_dd > 0 else 0
        if total_dd_pct > result.max_total_drawdown_pct:
            result.max_total_drawdown_pct = total_dd_pct
        
        if current_phase == 1:
            phase1_profit = (balance - phase1_start_balance) / phase1_start_balance
            if phase1_profit >= phase1_target:
                result.phase1_passed = True
                result.phase1_profit_pct = phase1_profit * 100
                result.phase1_days = trading_day_count
                phase1_complete_day = trading_day_count
                
                current_phase = 2
                phase2_start_balance = balance
                print(f"[Challenge Simulator] Phase 1 passed on day {trading_day_count}: +{phase1_profit*100:.1f}%")
        elif current_phase == 2:
            phase2_profit = (balance - phase2_start_balance) / phase2_start_balance
            if phase2_profit >= phase2_target:
                result.phase2_passed = True
                result.phase2_profit_pct = phase2_profit * 100
                result.phase2_days = trading_day_count - phase1_complete_day
                phase2_complete_day = trading_day_count
                print(f"[Challenge Simulator] Phase 2 passed on day {trading_day_count}: +{phase2_profit*100:.1f}%")
                break
    
    result.trading_days = len(daily_pnl)
    
    min_day_profit_usd = account_size * min_profit_per_day
    result.profitable_days = sum(1 for pnl in daily_pnl.values() if pnl >= min_day_profit_usd)
    
    result.total_profit_usd = balance - account_size
    result.total_profit_pct = (balance - account_size) / account_size * 100
    
    if result.phase1_passed and result.phase2_passed:
        result.both_passed = True
        result.days_to_pass = phase2_complete_day
    
    if result.daily_loss_violations > 0:
        result.phase1_passed = False
        result.phase2_passed = False
        result.both_passed = False
        result.failure_reason = f"Daily loss limit breached {result.daily_loss_violations} time(s)"
    elif result.total_loss_violations > 0:
        result.phase1_passed = False
        result.phase2_passed = False
        result.both_passed = False
        result.failure_reason = f"Total loss limit breached {result.total_loss_violations} time(s)"
    elif not result.phase1_passed:
        result.failure_reason = f"Phase 1 target ({phase1_target*100:.0f}%) not reached"
    elif not result.phase2_passed:
        result.failure_reason = f"Phase 2 target ({phase2_target*100:.0f}%) not reached after Phase 1"
    
    return result


def format_challenge_result(result: ChallengeResult) -> str:
    """Format challenge result for Discord or console output."""
    month_name = calendar.month_name[result.month]
    
    lines = [
        f"**Challenge Simulation: {month_name} {result.year}**",
        "",
    ]
    
    if result.both_passed:
        lines.append(f"Phase 1: PASSED (+{result.phase1_profit_pct:.1f}% in {result.phase1_days} days)")
        lines.append(f"Phase 2: PASSED (+{result.phase2_profit_pct:.1f}% in {result.phase2_days} days)")
        lines.append("")
        lines.append(f"**Passed in: {result.days_to_pass} trading days**")
        lines.append(f"**Total Profit: +{result.total_profit_pct:.1f}% (+${result.total_profit_usd:,.0f})**")
        lines.append(f"**Total Trades: {result.total_trades}**")
    else:
        lines.append(f"Phase 1: {'PASSED' if result.phase1_passed else 'FAILED'}")
        lines.append(f"Phase 2: {'PASSED' if result.phase2_passed else 'FAILED'}")
        lines.append("")
        lines.append(f"**Result: FAILED**")
        lines.append(f"Reason: {result.failure_reason}")
        lines.append("")
        lines.append(f"Final P&L: {'+' if result.total_profit_pct >= 0 else ''}{result.total_profit_pct:.1f}% (${result.total_profit_usd:+,.0f})")
        lines.append(f"Total Trades: {result.total_trades}")
    
    lines.append("")
    lines.append("**Risk Metrics:**")
    lines.append(f"  Max Daily Drawdown: -{result.max_daily_drawdown_pct:.1f}%")
    lines.append(f"  Max Total Drawdown: -{result.max_total_drawdown_pct:.1f}%")
    lines.append(f"  Daily Loss Violations: {result.daily_loss_violations}")
    lines.append(f"  Total Loss Violations: {result.total_loss_violations}")
    lines.append(f"  Trading Days: {result.trading_days}")
    lines.append(f"  Profitable Days: {result.profitable_days}")
    
    return "\n".join(lines)


def run_yearly_challenge_analysis(
    year: int,
    profile: Optional[AccountProfile] = None,
) -> List[ChallengeResult]:
    """
    Run challenge simulations for all 12 months of a year.
    
    Args:
        year: Calendar year to analyze
        profile: Account profile to use
    
    Returns:
        List of ChallengeResult for each month
    """
    results = []
    
    print(f"\n{'='*60}")
    print(f"YEARLY CHALLENGE ANALYSIS: {year}")
    print(f"{'='*60}")
    
    for month in range(1, 13):
        result = simulate_challenge_for_month(year, month, profile)
        results.append(result)
        
        status = "PASS" if result.both_passed else "FAIL"
        print(f"{calendar.month_abbr[month]} {year}: {status} | "
              f"P&L: {result.total_profit_pct:+.1f}% | "
              f"Trades: {result.total_trades} | "
              f"Days: {result.trading_days}")
    
    passed_months = sum(1 for r in results if r.both_passed)
    print(f"\n{'='*60}")
    print(f"SUMMARY: {passed_months}/12 months would pass the challenge")
    print(f"{'='*60}\n")
    
    return results


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) >= 3:
        try:
            month = int(sys.argv[1])
            year = int(sys.argv[2])
            
            if not 1 <= month <= 12:
                print("Month must be between 1 and 12")
                sys.exit(1)
            if not 2020 <= year <= 2030:
                print("Year must be between 2020 and 2030")
                sys.exit(1)
            
            result = simulate_challenge_for_month(year, month)
            print("\n" + format_challenge_result(result))
        except ValueError:
            print("Usage: python challenge_simulator.py <month> <year>")
            print("Example: python challenge_simulator.py 9 2024")
            sys.exit(1)
    else:
        current_year = datetime.now().year
        results = run_yearly_challenge_analysis(current_year)
