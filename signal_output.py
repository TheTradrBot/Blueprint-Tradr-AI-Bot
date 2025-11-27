"""
Signal Output Module for Blueprint Trader AI.

Provides a clean interface for exporting trade signals
to external systems like MT5 execution bots.

Designed for integration with:
- MetaTrader5 Python library on Windows VPS
- Webhooks and APIs
- File-based signal passing

Signal format includes all necessary data for order execution:
- Symbol (MT5 format)
- Direction (BUY/SELL)
- Entry price, Stop Loss, Take Profits
- Position sizing (lots)
- Risk metrics
- Unique signal ID
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, List, Dict
import json
import hashlib

from config import ACCOUNT_SIZE, RISK_PER_TRADE_PCT, ACTIVE_ACCOUNT_PROFILE
from position_sizing import calculate_position_size_5ers
from risk_manager import get_risk_manager, RiskCheckResult


@dataclass
class MT5Signal:
    """
    Trade signal formatted for MT5 execution.
    
    All fields needed for automated order placement on MT5.
    """
    signal_id: str
    timestamp: str
    
    symbol: str
    symbol_mt5: str
    
    direction: str
    order_type: str
    
    entry_price: float
    stop_loss: float
    take_profit_1: Optional[float] = None
    take_profit_2: Optional[float] = None
    take_profit_3: Optional[float] = None
    
    lot_size: float = 0.01
    risk_usd: float = 0.0
    risk_pct: float = 0.0
    stop_pips: float = 0.0
    
    account_size: float = 10000
    profile_name: str = "The5ers 10K"
    
    confluence_score: int = 0
    status: str = "pending"
    
    notes: str = ""
    
    valid: bool = True
    rejection_reason: str = ""
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)
    
    def to_mt5_order_params(self) -> Dict:
        """
        Return parameters ready for MetaTrader5 order placement.
        
        Compatible with:
        mt5.order_send(request)
        """
        action = 0 if self.order_type == "MARKET" else 5
        order_type = 0 if self.direction == "BUY" else 1
        
        return {
            "action": action,
            "symbol": self.symbol_mt5,
            "volume": self.lot_size,
            "type": order_type,
            "price": self.entry_price,
            "sl": self.stop_loss,
            "tp": self.take_profit_1,
            "deviation": 20,
            "magic": int(self.signal_id[:8], 16) % 1000000,
            "comment": f"Blueprint_{self.signal_id}",
            "type_time": 0,
            "type_filling": 1,
        }


def oanda_to_mt5_symbol(oanda_symbol: str) -> str:
    """
    Convert OANDA symbol format to MT5 format.
    
    OANDA: EUR_USD, XAU_USD, NAS100_USD
    MT5:   EURUSD, XAUUSD, NAS100
    """
    parts = oanda_symbol.split("_")
    if len(parts) == 2:
        base, quote = parts
        if base in ("XAU", "XAG", "XPT", "XPD", "XCU"):
            return f"{base}{quote}"
        if base in ("NAS100", "SPX500", "US30"):
            return base
        if base in ("WTICO", "BCO", "NATGAS"):
            return base
        return f"{base}{quote}"
    return oanda_symbol.replace("_", "")


def generate_signal_id(symbol: str, direction: str, timestamp: Optional[datetime] = None) -> str:
    """Generate unique signal ID."""
    ts = timestamp or datetime.now(timezone.utc)
    data = f"{symbol}_{direction}_{ts.isoformat()}_{id(ts)}"
    return hashlib.md5(data.encode()).hexdigest()[:12].upper()


def create_signal_from_scan(
    scan_result,
    account_size: float = None,
    risk_pct: float = None,
    validate_risk: bool = True,
) -> MT5Signal:
    """
    Create an MT5-ready signal from a scan result.
    
    Args:
        scan_result: ScanResult from strategy.py
        account_size: Account balance (default: from profile)
        risk_pct: Risk per trade (default: from profile)
        validate_risk: Whether to check against risk manager
        
    Returns:
        MT5Signal ready for execution or with rejection_reason if invalid
    """
    if account_size is None:
        account_size = ACCOUNT_SIZE
    if risk_pct is None:
        risk_pct = RISK_PER_TRADE_PCT
    
    now = datetime.now(timezone.utc)
    signal_id = generate_signal_id(scan_result.symbol, scan_result.direction, now)
    
    if scan_result.entry is None or scan_result.stop_loss is None:
        return MT5Signal(
            signal_id=signal_id,
            timestamp=now.isoformat(),
            symbol=scan_result.symbol,
            symbol_mt5=oanda_to_mt5_symbol(scan_result.symbol),
            direction="BUY" if scan_result.direction == "bullish" else "SELL",
            order_type="MARKET",
            entry_price=0,
            stop_loss=0,
            confluence_score=scan_result.confluence_score,
            status="invalid",
            valid=False,
            rejection_reason="Missing entry or stop loss levels",
        )
    
    sizing = calculate_position_size_5ers(
        symbol=scan_result.symbol,
        entry_price=scan_result.entry,
        stop_price=scan_result.stop_loss,
        account_size=account_size,
        risk_pct=risk_pct,
    )
    
    risk_check_result = RiskCheckResult.ALLOWED
    risk_check_msg = ""
    
    if validate_risk:
        rm = get_risk_manager()
        risk_check_result, risk_check_msg = rm.can_add_trade(sizing["risk_usd"])
    
    is_valid = risk_check_result in (RiskCheckResult.ALLOWED, RiskCheckResult.WARNING_NEAR_LIMIT)
    status = "approved" if is_valid else "rejected"
    rejection = "" if is_valid else risk_check_msg
    
    return MT5Signal(
        signal_id=signal_id,
        timestamp=now.isoformat(),
        symbol=scan_result.symbol,
        symbol_mt5=oanda_to_mt5_symbol(scan_result.symbol),
        direction="BUY" if scan_result.direction == "bullish" else "SELL",
        order_type="MARKET",
        entry_price=scan_result.entry,
        stop_loss=scan_result.stop_loss,
        take_profit_1=scan_result.tp1,
        take_profit_2=scan_result.tp2,
        take_profit_3=scan_result.tp3,
        lot_size=sizing["lot_size"],
        risk_usd=sizing["risk_usd"],
        risk_pct=sizing["risk_pct"],
        stop_pips=sizing["stop_pips"],
        account_size=account_size,
        profile_name=ACTIVE_ACCOUNT_PROFILE.display_name,
        confluence_score=scan_result.confluence_score,
        status=status,
        notes=risk_check_msg if risk_check_result == RiskCheckResult.WARNING_NEAR_LIMIT else "",
        valid=is_valid,
        rejection_reason=rejection,
    )


def export_signals_to_file(signals: List[MT5Signal], filepath: str = "signals.json") -> str:
    """
    Export signals to JSON file for MT5 executor to consume.
    
    Args:
        signals: List of MT5Signal objects
        filepath: Output file path
        
    Returns:
        Path to exported file
    """
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": ACTIVE_ACCOUNT_PROFILE.display_name,
        "account_size": ACCOUNT_SIZE,
        "signals": [s.to_dict() for s in signals],
    }
    
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    
    return filepath


def get_pending_signals(signals: List[MT5Signal]) -> List[MT5Signal]:
    """Filter to only pending, valid signals."""
    return [s for s in signals if s.valid and s.status == "approved"]


def format_signal_summary(signal: MT5Signal) -> str:
    """Format signal for logging/display."""
    emoji = "🟢" if signal.direction == "BUY" else "🔴"
    status_emoji = "✅" if signal.valid else "❌"
    
    lines = [
        f"{status_emoji} {emoji} **{signal.symbol_mt5}** {signal.direction}",
        f"Entry: {signal.entry_price:.5f} | SL: {signal.stop_loss:.5f}",
        f"Lots: {signal.lot_size:.2f} | Risk: ${signal.risk_usd:,.0f} ({signal.risk_pct*100:.2f}%)",
        f"TP1: {signal.take_profit_1:.5f if signal.take_profit_1 else 'N/A'}",
        f"ID: {signal.signal_id} | Status: {signal.status.upper()}",
    ]
    
    if signal.rejection_reason:
        lines.append(f"Reason: {signal.rejection_reason}")
    
    return "\n".join(lines)
