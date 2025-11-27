"""
Risk Manager for Blueprint Trader AI.

Implements The5ers High Stakes risk rules:
- Daily loss tracking (5% limit)
- Total drawdown tracking (10% limit)
- Projected risk validation before new trades
- Trading time restrictions (Friday cutoff, news events)

Designed to prevent challenge failures by blocking trades
that would violate rules or get too close to limits.
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone
from typing import Optional, Dict, List, Tuple
from enum import Enum

from account_profiles import AccountProfile, get_active_profile


class RiskCheckResult(Enum):
    """Result of a risk check."""
    ALLOWED = "allowed"
    BLOCKED_DAILY_LOSS = "blocked_daily_loss"
    BLOCKED_TOTAL_LOSS = "blocked_total_loss"
    BLOCKED_OPEN_RISK = "blocked_open_risk"
    BLOCKED_CONCURRENT = "blocked_concurrent"
    BLOCKED_FRIDAY_CUTOFF = "blocked_friday_cutoff"
    BLOCKED_MONDAY_COOLDOWN = "blocked_monday_cooldown"
    BLOCKED_NEWS_EVENT = "blocked_news_event"
    WARNING_NEAR_LIMIT = "warning_near_limit"


@dataclass
class TradeRecord:
    """Record of an open or closed trade for risk tracking."""
    trade_id: str
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    lot_size: float
    risk_usd: float
    risk_pct: float
    entry_datetime: datetime
    exit_datetime: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl_usd: Optional[float] = None
    is_open: bool = True


@dataclass
class DailyPnL:
    """Track P&L for a specific trading day."""
    date: date
    realized_pnl_usd: float = 0.0
    unrealized_pnl_usd: float = 0.0
    trades_opened: int = 0
    trades_closed: int = 0
    
    @property
    def total_pnl_usd(self) -> float:
        return self.realized_pnl_usd + self.unrealized_pnl_usd
    
    def is_profitable_day(self, min_profit_usd: float) -> bool:
        """Check if this qualifies as a profitable day per The5ers rules."""
        return self.realized_pnl_usd >= min_profit_usd


class RiskManager:
    """
    Central risk management for prop firm challenges.
    
    Tracks:
    - Current open trades and their risk
    - Daily P&L for rule compliance
    - Total drawdown from starting balance
    - Trading time restrictions
    
    Validates new trades against all rules before allowing.
    """
    
    def __init__(self, profile: Optional[AccountProfile] = None):
        self.profile = profile or get_active_profile()
        self.starting_balance = self.profile.starting_balance
        self.current_balance = self.starting_balance
        self.peak_balance = self.starting_balance
        
        self.open_trades: Dict[str, TradeRecord] = {}
        self.closed_trades: List[TradeRecord] = []
        self.daily_pnl: Dict[date, DailyPnL] = {}
        
        self.current_phase = 1
        self.phase_start_balance = self.starting_balance
        
        self.news_events: List[Tuple[datetime, str]] = []
    
    def get_current_date(self) -> date:
        """Get current date in UTC."""
        return datetime.now(timezone.utc).date()
    
    def get_today_pnl(self) -> DailyPnL:
        """Get or create today's P&L record."""
        today = self.get_current_date()
        if today not in self.daily_pnl:
            self.daily_pnl[today] = DailyPnL(date=today)
        return self.daily_pnl[today]
    
    def get_open_risk_usd(self) -> float:
        """Total risk in USD from all open trades."""
        return sum(t.risk_usd for t in self.open_trades.values())
    
    def get_open_risk_pct(self) -> float:
        """Total risk as percentage of starting balance."""
        return self.get_open_risk_usd() / self.starting_balance
    
    def get_daily_loss_usd(self) -> float:
        """Current daily loss in USD (negative if loss)."""
        today_pnl = self.get_today_pnl()
        return today_pnl.total_pnl_usd
    
    def get_daily_loss_pct(self) -> float:
        """Current daily loss as percentage of starting balance."""
        return self.get_daily_loss_usd() / self.starting_balance
    
    def get_total_drawdown_usd(self) -> float:
        """Total drawdown from starting balance in USD."""
        return self.starting_balance - self.current_balance
    
    def get_total_drawdown_pct(self) -> float:
        """Total drawdown from starting balance as percentage."""
        return self.get_total_drawdown_usd() / self.starting_balance
    
    def get_projected_loss_usd(self) -> float:
        """
        Projected loss if all open trades hit their stop loss.
        This is the maximum possible loss from current positions.
        """
        return self.get_open_risk_usd()
    
    def get_projected_daily_loss_pct(self) -> float:
        """Projected daily loss if all open trades hit SL."""
        daily_realized = self.get_today_pnl().realized_pnl_usd
        projected_loss = daily_realized - self.get_projected_loss_usd()
        return projected_loss / self.starting_balance
    
    def get_projected_total_loss_pct(self) -> float:
        """Projected total loss if all open trades hit SL."""
        current_dd = self.get_total_drawdown_usd()
        projected_loss = current_dd + self.get_projected_loss_usd()
        return projected_loss / self.starting_balance
    
    def can_add_trade(
        self,
        risk_usd: float,
        check_time: Optional[datetime] = None,
    ) -> Tuple[RiskCheckResult, str]:
        """
        Check if a new trade with given risk can be added.
        
        Returns:
            Tuple of (result, message) where result indicates if trade is allowed
            and message provides details.
        """
        now = check_time or datetime.now(timezone.utc)
        
        time_check = self._check_trading_time(now)
        if time_check[0] != RiskCheckResult.ALLOWED:
            return time_check
        
        if len(self.open_trades) >= self.profile.max_concurrent_trades:
            return (
                RiskCheckResult.BLOCKED_CONCURRENT,
                f"Max {self.profile.max_concurrent_trades} concurrent trades allowed. "
                f"Currently have {len(self.open_trades)} open."
            )
        
        new_open_risk = self.get_open_risk_usd() + risk_usd
        max_open_risk = self.profile.get_max_open_risk_usd()
        if new_open_risk > max_open_risk:
            return (
                RiskCheckResult.BLOCKED_OPEN_RISK,
                f"Adding this trade would exceed max open risk of "
                f"${max_open_risk:,.0f} ({self.profile.max_open_risk_pct*100:.1f}%). "
                f"Current open risk: ${self.get_open_risk_usd():,.0f}."
            )
        
        daily_pnl = self.get_today_pnl().realized_pnl_usd
        projected_daily_loss = daily_pnl - new_open_risk
        safe_daily_limit = self.starting_balance * self.profile.get_safe_daily_loss_limit()
        
        if abs(projected_daily_loss) > safe_daily_limit:
            return (
                RiskCheckResult.BLOCKED_DAILY_LOSS,
                f"Adding this trade risks breaching daily loss limit. "
                f"Daily P&L: ${daily_pnl:,.0f}, Projected loss: ${projected_daily_loss:,.0f}, "
                f"Safe limit: ${safe_daily_limit:,.0f}."
            )
        
        current_dd = self.get_total_drawdown_usd()
        projected_total_loss = current_dd + new_open_risk
        safe_total_limit = self.starting_balance * self.profile.get_safe_total_loss_limit()
        
        if projected_total_loss > safe_total_limit:
            return (
                RiskCheckResult.BLOCKED_TOTAL_LOSS,
                f"Adding this trade risks breaching total loss limit. "
                f"Current DD: ${current_dd:,.0f}, Projected: ${projected_total_loss:,.0f}, "
                f"Safe limit: ${safe_total_limit:,.0f}."
            )
        
        warning_threshold = 0.7
        daily_usage = abs(projected_daily_loss) / safe_daily_limit
        total_usage = projected_total_loss / safe_total_limit
        
        if daily_usage > warning_threshold or total_usage > warning_threshold:
            return (
                RiskCheckResult.WARNING_NEAR_LIMIT,
                f"Trade allowed but approaching limits. "
                f"Daily: {daily_usage*100:.0f}% of limit, "
                f"Total: {total_usage*100:.0f}% of limit."
            )
        
        return (
            RiskCheckResult.ALLOWED,
            f"Trade approved. Open risk: ${new_open_risk:,.0f} / ${max_open_risk:,.0f}."
        )
    
    def _check_trading_time(self, now: datetime) -> Tuple[RiskCheckResult, str]:
        """Check if current time allows new trades."""
        if now.weekday() == 4:
            if now.hour >= self.profile.friday_cutoff_hour_utc:
                return (
                    RiskCheckResult.BLOCKED_FRIDAY_CUTOFF,
                    f"No new trades after {self.profile.friday_cutoff_hour_utc}:00 UTC on Friday. "
                    f"Current time: {now.strftime('%H:%M')} UTC."
                )
        
        if now.weekday() == 0:
            market_open = now.replace(hour=0, minute=0, second=0, microsecond=0)
            hours_since_open = (now - market_open).total_seconds() / 3600
            if hours_since_open < self.profile.monday_cooldown_hours:
                return (
                    RiskCheckResult.BLOCKED_MONDAY_COOLDOWN,
                    f"Monday cooldown in effect. Wait {self.profile.monday_cooldown_hours}h "
                    f"after market open. Time remaining: "
                    f"{self.profile.monday_cooldown_hours - hours_since_open:.1f}h."
                )
        
        for event_time, event_name in self.news_events:
            blackout_start = event_time - timedelta(minutes=self.profile.news_blackout_minutes)
            blackout_end = event_time + timedelta(minutes=self.profile.news_blackout_minutes)
            if blackout_start <= now <= blackout_end:
                return (
                    RiskCheckResult.BLOCKED_NEWS_EVENT,
                    f"News blackout in effect for: {event_name}. "
                    f"Wait until {blackout_end.strftime('%H:%M')} UTC."
                )
        
        return (RiskCheckResult.ALLOWED, "Trading time OK.")
    
    def add_news_event(self, event_time: datetime, event_name: str) -> None:
        """Add a high-impact news event to block trading around."""
        self.news_events.append((event_time, event_name))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        self.news_events = [(t, n) for t, n in self.news_events if t > cutoff]
    
    def open_trade(self, trade: TradeRecord) -> None:
        """Record a new open trade."""
        self.open_trades[trade.trade_id] = trade
        today_pnl = self.get_today_pnl()
        today_pnl.trades_opened += 1
    
    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        pnl_usd: float,
        exit_datetime: Optional[datetime] = None,
    ) -> Optional[TradeRecord]:
        """Record a trade closure."""
        if trade_id not in self.open_trades:
            return None
        
        trade = self.open_trades.pop(trade_id)
        trade.is_open = False
        trade.exit_price = exit_price
        trade.exit_datetime = exit_datetime or datetime.now(timezone.utc)
        trade.pnl_usd = pnl_usd
        
        self.closed_trades.append(trade)
        
        self.current_balance += pnl_usd
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
        
        today_pnl = self.get_today_pnl()
        today_pnl.realized_pnl_usd += pnl_usd
        today_pnl.trades_closed += 1
        
        return trade
    
    def update_unrealized_pnl(self, total_unrealized: float) -> None:
        """Update today's unrealized P&L from all open positions."""
        today_pnl = self.get_today_pnl()
        today_pnl.unrealized_pnl_usd = total_unrealized
    
    def get_phase_progress(self) -> Dict:
        """Get current phase progress."""
        phase = self.profile.get_phase(self.current_phase)
        if not phase:
            return {"phase": self.current_phase, "status": "unknown"}
        
        current_profit = self.current_balance - self.phase_start_balance
        current_profit_pct = current_profit / self.phase_start_balance
        target_profit = self.phase_start_balance * phase.profit_target_pct
        target_pct = phase.profit_target_pct
        
        progress_pct = (current_profit_pct / target_pct) * 100 if target_pct > 0 else 0
        
        min_day_profit = self.phase_start_balance * phase.min_profit_per_day_pct
        profitable_days = sum(
            1 for d in self.daily_pnl.values()
            if d.is_profitable_day(min_day_profit)
        )
        
        return {
            "phase": self.current_phase,
            "phase_name": phase.name,
            "current_profit_usd": current_profit,
            "current_profit_pct": current_profit_pct * 100,
            "target_profit_usd": target_profit,
            "target_profit_pct": target_pct * 100,
            "progress_pct": min(progress_pct, 100),
            "profitable_days": profitable_days,
            "min_profitable_days": phase.min_profitable_days,
            "days_remaining": max(0, phase.min_profitable_days - profitable_days),
            "phase_complete": (
                current_profit_pct >= target_pct and
                profitable_days >= phase.min_profitable_days
            ),
        }
    
    def get_risk_summary(self) -> Dict:
        """Get comprehensive risk status summary."""
        return {
            "profile": self.profile.display_name,
            "starting_balance": self.starting_balance,
            "current_balance": self.current_balance,
            
            "open_trades": len(self.open_trades),
            "max_concurrent": self.profile.max_concurrent_trades,
            
            "open_risk_usd": self.get_open_risk_usd(),
            "open_risk_pct": self.get_open_risk_pct() * 100,
            "max_open_risk_pct": self.profile.max_open_risk_pct * 100,
            
            "daily_pnl_usd": self.get_daily_loss_usd(),
            "daily_pnl_pct": self.get_daily_loss_pct() * 100,
            "max_daily_loss_pct": self.profile.max_daily_loss_pct * 100,
            
            "total_drawdown_usd": self.get_total_drawdown_usd(),
            "total_drawdown_pct": self.get_total_drawdown_pct() * 100,
            "max_total_loss_pct": self.profile.max_total_loss_pct * 100,
            
            "projected_daily_loss_pct": abs(self.get_projected_daily_loss_pct()) * 100,
            "projected_total_loss_pct": self.get_projected_total_loss_pct() * 100,
            
            "phase_progress": self.get_phase_progress(),
        }
    
    def reset(self) -> None:
        """Reset risk manager to initial state."""
        self.current_balance = self.starting_balance
        self.peak_balance = self.starting_balance
        self.open_trades.clear()
        self.closed_trades.clear()
        self.daily_pnl.clear()
        self.current_phase = 1
        self.phase_start_balance = self.starting_balance


RISK_MANAGER = RiskManager()


def get_risk_manager() -> RiskManager:
    """Get the global risk manager instance."""
    return RISK_MANAGER
