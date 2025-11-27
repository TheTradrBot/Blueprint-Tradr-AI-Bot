"""
Trade State Persistence for Blueprint Trader AI.

Maintains persistent record of:
- Posted trade announcements (to prevent duplicate Discord posts on restart)
- Posted trade updates (TP hits, SL hits)
- Bot startup timestamp for filtering old signals

This ensures the Discord bot only posts NEW trades and updates,
not historical ones that were already announced in previous sessions.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Any

from strategy import ScanResult
from data import get_ohlcv


STATE_FILE = "trade_state.json"

_active_trades: Dict[str, ScanResult] = {}


def _key(res: ScanResult) -> str:
    return f"{res.symbol}:{res.direction}"


def register_trade(res: ScanResult) -> None:
    """
    Register or update an active trade idea.
    Newest signal for a (symbol, direction) pair overwrites older one.
    """
    _active_trades[_key(res)] = res


def list_trades() -> List[ScanResult]:
    """
    Return a list of currently tracked trades.
    """
    return list(_active_trades.values())


def evaluate_trades_for_updates() -> List[Tuple[ScanResult, str, float, float]]:
    """
    Check each active trade for TP/SL hits using the latest H4 candle.

    Returns a list of events:
      (ScanResult, event_type, event_price, event_rr)

    event_type in {"TP1", "TP2", "TP3", "SL"}
    event_rr is the R-multiple at that level (based on entry & SL), or NaN.
    """
    events: List[Tuple[ScanResult, str, float, float]] = []

    for trade in _active_trades.values():
        if getattr(trade, "is_closed", False):
            continue

        candles = get_ohlcv(trade.symbol, timeframe="H4", count=1)
        if not candles:
            continue

        c = candles[-1]
        high = c["high"]
        low = c["low"]

        entry = trade.entry
        sl = trade.stop_loss

        if entry is None or sl is None:
            continue

        if trade.direction == "bullish":
            risk = entry - sl
        else:
            risk = sl - entry

        if risk <= 0:
            risk = None

        if trade.direction == "bullish":
            if not getattr(trade, "sl_hit", False) and low <= sl:
                trade.sl_hit = True
                trade.is_closed = True
                trade.status = "closed - SL hit"
                rr = -1.0 if risk else float("nan")
                events.append((trade, "SL", sl, rr))
                continue

            if trade.tp1 is not None and (not getattr(trade, "tp1_hit", False)) and high >= trade.tp1:
                trade.tp1_hit = True
                rr = ((trade.tp1 - entry) / risk) if risk else float("nan")
                events.append((trade, "TP1", trade.tp1, rr))

            if trade.tp2 is not None and (not getattr(trade, "tp2_hit", False)) and high >= trade.tp2:
                trade.tp2_hit = True
                rr = ((trade.tp2 - entry) / risk) if risk else float("nan")
                events.append((trade, "TP2", trade.tp2, rr))

            if trade.tp3 is not None and (not getattr(trade, "tp3_hit", False)) and high >= trade.tp3:
                trade.tp3_hit = True
                trade.is_closed = True
                trade.status = "closed - TP3 hit"
                rr = ((trade.tp3 - entry) / risk) if risk else float("nan")
                events.append((trade, "TP3", trade.tp3, rr))

        else:
            if not getattr(trade, "sl_hit", False) and high >= sl:
                trade.sl_hit = True
                trade.is_closed = True
                trade.status = "closed - SL hit"
                rr = -1.0 if risk else float("nan")
                events.append((trade, "SL", sl, rr))
                continue

            if trade.tp1 is not None and (not getattr(trade, "tp1_hit", False)) and low <= trade.tp1:
                trade.tp1_hit = True
                rr = ((entry - trade.tp1) / risk) if risk else float("nan")
                events.append((trade, "TP1", trade.tp1, rr))

            if trade.tp2 is not None and (not getattr(trade, "tp2_hit", False)) and low <= trade.tp2:
                trade.tp2_hit = True
                rr = ((entry - trade.tp2) / risk) if risk else float("nan")
                events.append((trade, "TP2", trade.tp2, rr))

            if trade.tp3 is not None and (not getattr(trade, "tp3_hit", False)) and low <= trade.tp3:
                trade.tp3_hit = True
                trade.is_closed = True
                trade.status = "closed - TP3 hit"
                rr = ((entry - trade.tp3) / risk) if risk else float("nan")
                events.append((trade, "TP3", trade.tp3, rr))

    return events


class TradeStateManager:
    """
    Manages persistent state for trade announcements.
    
    Tracks:
    - posted_trades: Set of trade IDs that have been announced
    - posted_updates: Dict mapping trade_id -> list of update types already posted
    - bot_startup_time: When the current bot session started
    - last_scan_time: When the last scan was completed
    """
    
    def __init__(self, state_file: str = STATE_FILE):
        self.state_file = Path(state_file)
        self.posted_trades: Set[str] = set()
        self.posted_updates: Dict[str, Set[str]] = {}
        self.bot_startup_time: Optional[datetime] = None
        self.last_scan_time: Optional[datetime] = None
        self._load_state()
    
    def _load_state(self) -> None:
        """Load state from persistent file."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                
                self.posted_trades = set(data.get("posted_trades", []))
                
                updates_raw = data.get("posted_updates", {})
                self.posted_updates = {k: set(v) for k, v in updates_raw.items()}
                
                if data.get("last_scan_time"):
                    self.last_scan_time = datetime.fromisoformat(data["last_scan_time"])
                
                print(f"[TradeState] Loaded state: {len(self.posted_trades)} posted trades, "
                      f"{sum(len(v) for v in self.posted_updates.values())} posted updates")
            except Exception as e:
                print(f"[TradeState] Error loading state: {e}")
                self._reset_state()
        else:
            print("[TradeState] No existing state file, starting fresh")
            self._reset_state()
        
        self.bot_startup_time = datetime.now(timezone.utc)
    
    def _reset_state(self) -> None:
        """Reset to clean state."""
        self.posted_trades = set()
        self.posted_updates = {}
        self.last_scan_time = None
    
    def _save_state(self) -> None:
        """Save state to persistent file."""
        try:
            data = {
                "posted_trades": list(self.posted_trades),
                "posted_updates": {k: list(v) for k, v in self.posted_updates.items()},
                "last_scan_time": self.last_scan_time.isoformat() if self.last_scan_time else None,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
            
            with open(self.state_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[TradeState] Error saving state: {e}")
    
    def generate_trade_id(self, symbol: str, direction: str, entry: Optional[float] = None) -> str:
        """
        Generate a unique trade ID for deduplication.
        
        Format: {symbol}_{direction}_{entry_rounded}
        This allows the same symbol to have multiple trades if entry differs significantly.
        """
        if entry is not None:
            if entry > 100:
                entry_key = f"{entry:.1f}"
            elif entry > 1:
                entry_key = f"{entry:.3f}"
            else:
                entry_key = f"{entry:.5f}"
            return f"{symbol}_{direction}_{entry_key}"
        else:
            return f"{symbol}_{direction}"
    
    def is_trade_posted(self, trade_id: str) -> bool:
        """Check if a trade has already been posted to Discord."""
        return trade_id in self.posted_trades
    
    def mark_trade_posted(self, trade_id: str) -> None:
        """Mark a trade as posted to Discord."""
        self.posted_trades.add(trade_id)
        self._save_state()
        print(f"[TradeState] Marked trade as posted: {trade_id}")
    
    def is_update_posted(self, trade_id: str, update_type: str) -> bool:
        """
        Check if a specific update for a trade has been posted.
        
        update_type: "tp1", "tp2", "tp3", "sl", "closed", etc.
        """
        if trade_id not in self.posted_updates:
            return False
        return update_type in self.posted_updates[trade_id]
    
    def mark_update_posted(self, trade_id: str, update_type: str) -> None:
        """Mark a specific update as posted."""
        if trade_id not in self.posted_updates:
            self.posted_updates[trade_id] = set()
        self.posted_updates[trade_id].add(update_type)
        self._save_state()
        print(f"[TradeState] Marked update as posted: {trade_id} -> {update_type}")
    
    def remove_trade(self, trade_id: str) -> None:
        """Remove a trade from tracking (when fully closed)."""
        self.posted_trades.discard(trade_id)
        self.posted_updates.pop(trade_id, None)
        self._save_state()
    
    def update_scan_time(self) -> None:
        """Record the current time as the last scan time."""
        self.last_scan_time = datetime.now(timezone.utc)
        self._save_state()
    
    def get_seconds_since_startup(self) -> float:
        """Get seconds elapsed since bot startup."""
        if not self.bot_startup_time:
            return 0.0
        return (datetime.now(timezone.utc) - self.bot_startup_time).total_seconds()
    
    def should_post_new_trade(self, trade_id: str, signal_time: Optional[datetime] = None) -> bool:
        """
        Determine if a trade signal should be posted as a new trade.
        
        Returns True only if:
        1. Trade has not been posted before, AND
        2. Either no signal_time provided, or signal is after bot startup
        """
        if self.is_trade_posted(trade_id):
            return False
        
        if signal_time and self.bot_startup_time:
            if signal_time < self.bot_startup_time:
                print(f"[TradeState] Signal {trade_id} is from before startup, skipping")
                return False
        
        return True
    
    def get_state_summary(self) -> Dict[str, Any]:
        """Get a summary of current state for debugging."""
        return {
            "posted_trades_count": len(self.posted_trades),
            "posted_updates_count": sum(len(v) for v in self.posted_updates.values()),
            "bot_startup_time": self.bot_startup_time.isoformat() if self.bot_startup_time else None,
            "last_scan_time": self.last_scan_time.isoformat() if self.last_scan_time else None,
            "seconds_since_startup": self.get_seconds_since_startup(),
        }
    
    def clear_state(self) -> None:
        """Clear all state (for testing/reset)."""
        self._reset_state()
        self._save_state()
        print("[TradeState] State cleared")


TRADE_STATE = TradeStateManager()


def get_trade_state() -> TradeStateManager:
    """Get the global trade state manager instance."""
    return TRADE_STATE
