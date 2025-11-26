# backtest.py
from __future__ import annotations

from datetime import datetime, date, timedelta, timezone
from typing import List, Dict, Tuple, Optional
import inspect

from data import get_ohlcv
from config import SIGNAL_MODE
from strategy import (
    _infer_trend,
    _pick_direction_from_bias,
    _compute_confluence_flags as _strategy_compute_confluence_flags,
)

# ======================================================
# Strategy confluence adapter (handles old/new signatures)
# ======================================================

# Detect how many parameters the strategy function has
_STRATEGY_CONF_SIG = inspect.signature(_strategy_compute_confluence_flags)
_STRATEGY_CONF_PARAM_COUNT = len(_STRATEGY_CONF_SIG.parameters)


def _strategy_confluence_adapter(
    monthly_candles: List[Dict],
    weekly_candles: List[Dict],
    daily_candles: List[Dict],
    h4_candles: List[Dict],
    direction: str,
):
    """
    Adapter so backtest works with both old and new versions of
    strategy._compute_confluence_flags.

    - New version: _compute_confluence_flags(monthly, weekly, daily, h4, direction)
    - Old version: _compute_confluence_flags(monthly, weekly, daily, h4)
    """
    if _STRATEGY_CONF_PARAM_COUNT >= 5:
        # New version with 'direction'
        return _strategy_compute_confluence_flags(
            monthly_candles,
            weekly_candles,
            daily_candles,
            h4_candles,
            direction,
        )
    else:
        # Old version without 'direction'
        return _strategy_compute_confluence_flags(
            monthly_candles,
            weekly_candles,
            daily_candles,
            h4_candles,
        )


# ======================================================
# Date & time helpers
# ======================================================

def _parse_partial_date(s: str, for_start: bool) -> Optional[date]:
    """
    Parse things like:
      - 'Jan 2024'
      - 'January 2024'
      - '4 Sep 2025'
      - '2024-01-01'
      - 'Now' / 'Today'
    """
    s = s.strip()
    if not s:
        return None

    lower = s.lower()
    if lower in ("now", "today"):
        return date.today()

    # Try full day-month-year first
    fmts = [
        "%d %b %Y",
        "%d %B %Y",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(s, fmt).date()
            return dt
        except Exception:
            pass

    # Try month + year only
    month_fmts = ["%b %Y", "%B %Y"]
    for fmt in month_fmts:
        try:
            dt = datetime.strptime(s, fmt).date()
            if for_start:
                # first day of month
                return date(dt.year, dt.month, 1)
            else:
                # last day of month
                if dt.month == 12:
                    return date(dt.year, 12, 31)
                else:
                    next_month = date(dt.year, dt.month + 1, 1)
                    return next_month - timedelta(days=1)
        except Exception:
            pass

    return None


def _parse_period(period_str: str) -> Tuple[Optional[date], Optional[date]]:
    """
    Parse "Jan 2024 - Sep 2024" or "4 Sep 2025 - Now" into (start_date, end_date).
    If parsing fails, returns (None, None) and we later fall back to last N candles.
    """
    s = period_str.strip()
    if "-" in s:
        left, right = s.split("-", 1)
        left = left.strip()
        right = right.strip()
    else:
        left, right = s, "now"

    start = _parse_partial_date(left, for_start=True)
    end = _parse_partial_date(right, for_start=False)

    # ensure start <= end if both exist
    if start and end and start > end:
        start, end = end, start

    return start, end


def _candle_to_datetime(candle: Dict) -> Optional[datetime]:
    """
    Try to get a datetime from a generic OANDA-style candle dict.
    """
    t = candle.get("time") or candle.get("timestamp") or candle.get("date")
    if t is None:
        return None

    if isinstance(t, datetime):
        return t
    if isinstance(t, date):
        return datetime(t.year, t.month, t.day, tzinfo=timezone.utc)
    if isinstance(t, (int, float)):
        # assume unix timestamp (seconds)
        try:
            return datetime.utcfromtimestamp(t).replace(tzinfo=timezone.utc)
        except Exception:
            return None

    if isinstance(t, str):
        s = t.strip()

        # Common OANDA style: '2024-01-02T21:00:00.000000000Z'
        try:
            s2 = s.replace("Z", "+00:00")
            if "." in s2:
                head, tail = s2.split(".", 1)
                decimals = "".join(ch for ch in tail if ch.isdigit())
                decimals = decimals[:6]  # microseconds
                rest = tail[len(decimals):]
                s2 = f"{head}.{decimals}{rest}"
            return datetime.fromisoformat(s2)
        except Exception:
            pass

        # Simple fallbacks
        fmts = [
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
        ]
        for fmt in fmts:
            try:
                return datetime.strptime(s[: len(fmt)], fmt)
            except Exception:
                continue

    return None


def _candle_to_date(candle: Dict) -> Optional[date]:
    dt = _candle_to_datetime(candle)
    return dt.date() if dt else None


def _build_date_list(candles: List[Dict]) -> List[Optional[date]]:
    return [_candle_to_date(c) for c in candles]


# ======================================================
# Trade exit helper
# ======================================================

def _maybe_exit_trade(
    trade: Dict,
    high: float,
    low: float,
    exit_date: date,
) -> Optional[Dict]:
    """
    Given an open trade and a candle's high/low, decide if TP/SL is hit.
    We use a conservative assumption: if SL and TP are both touched inside
    one candle, we assume SL is hit first.
    Returns a closed-trade dict or None if trade stays open.
    """
    direction = trade["direction"]
    entry = trade["entry"]
    sl = trade["sl"]
    tp1 = trade["tp1"]
    tp2 = trade["tp2"]
    tp3 = trade["tp3"]
    risk = trade["risk"]

    if direction == "bullish":
        hit_sl = low <= sl
        hit_tp3 = tp3 is not None and high >= tp3
        hit_tp2 = tp2 is not None and high >= tp2
        hit_tp1 = tp1 is not None and high >= tp1

        if hit_sl and not (hit_tp1 or hit_tp2 or hit_tp3):
            rr = -1.0
            reason = "SL"
        elif hit_sl and (hit_tp1 or hit_tp2 or hit_tp3):
            # Worst-case: assume SL first
            rr = -1.0
            reason = "SL"
        elif hit_tp3:
            rr = (tp3 - entry) / risk
            reason = "TP3"
        elif hit_tp2:
            rr = (tp2 - entry) / risk
            reason = "TP2"
        elif hit_tp1:
            rr = (tp1 - entry) / risk
            reason = "TP1"
        else:
            return None

    else:  # bearish
        hit_sl = high >= sl
        hit_tp3 = tp3 is not None and low <= tp3
        hit_tp2 = tp2 is not None and low <= tp2
        hit_tp1 = tp1 is not None and low <= tp1

        if hit_sl and not (hit_tp1 or hit_tp2 or hit_tp3):
            rr = -1.0
            reason = "SL"
        elif hit_sl and (hit_tp1 or hit_tp2 or hit_tp3):
            rr = -1.0
            reason = "SL"
        elif hit_tp3:
            rr = (entry - tp3) / risk
            reason = "TP3"
        elif hit_tp2:
            rr = (entry - tp2) / risk
            reason = "TP2"
        elif hit_tp1:
            rr = (entry - tp1) / risk
            reason = "TP1"
        else:
            return None

    return {
        "entry_date": trade["entry_date"].isoformat(),
        "exit_date": exit_date.isoformat(),
        "direction": direction,
        "rr": rr,
        "exit_reason": reason,
    }


# ======================================================
# Core backtest
# ======================================================

def run_backtest(asset: str, period: str) -> Dict:
    """
    Backtest the *current* Blueprint strategy logic on Daily candles.

    Notes / approximations:
      - Uses the same 7-pillar confluence logic as /scan, via the adapter.
      - Evaluates logic on each Daily close in the chosen period.
      - A trade is opened only when the signal would be 'active'
        (i.e. 4H confirmation + enough confluence + valid R/R).
      - One trade at a time per asset.
      - Execution is approximated with Daily high/low for TP/SL.
    """
    # 1) Fetch data (keep counts moderate to avoid OANDA 'count' limit)
    daily = get_ohlcv(asset, timeframe="D", count=1500)
    if not daily:
        return {
            "asset": asset,
            "period": period,
            "total_trades": 0,
            "win_rate": 0.0,
            "net_return_pct": 0.0,
            "trades": [],
            "notes": "No Daily data available for this asset.",
        }

    weekly = get_ohlcv(asset, timeframe="W", count=400) or []
    monthly = get_ohlcv(asset, timeframe="M", count=240) or []
    h4 = get_ohlcv(asset, timeframe="H4", count=1500) or []

    daily_dates = _build_date_list(daily)
    weekly_dates = _build_date_list(weekly)
    monthly_dates = _build_date_list(monthly)
    h4_dates = _build_date_list(h4)

    # 2) Build list of indices to test based on the requested period
    start_req, end_req = _parse_period(period)

    indices: List[int] = []

    if start_req or end_req:
        # Determine fallback start/end if missing
        last_d = next((d for d in reversed(daily_dates) if d is not None), None)
        first_d = next((d for d in daily_dates if d is not None), None)

        end_date = end_req or last_d
        start_date = start_req or first_d

        if start_date is None or end_date is None:
            # Can't interpret dates -> fallback to last 260 candles
            start_idx = max(0, len(daily) - 260)
            indices = list(range(start_idx, len(daily)))
            period_label = "Last 260 Daily candles"
        else:
            for i, d in enumerate(daily_dates):
                if d is None:
                    continue
                if start_date <= d <= end_date:
                    indices.append(i)

            if not indices:
                # no candles in that period -> fallback
                start_idx = max(0, len(daily) - 260)
                indices = list(range(start_idx, len(daily)))
                period_label = "Last 260 Daily candles"
            else:
                sd = daily_dates[indices[0]]
                ed = daily_dates[indices[-1]]
                if sd and ed:
                    period_label = f"{sd.isoformat()} - {ed.isoformat()}"
                else:
                    period_label = period
    else:
        # No usable period -> fallback to last 260 candles
        start_idx = max(0, len(daily) - 260)
        indices = list(range(start_idx, len(daily)))
        period_label = "Last 260 Daily candles"

    if not indices:
        return {
            "asset": asset,
            "period": period,
            "total_trades": 0,
            "win_rate": 0.0,
            "net_return_pct": 0.0,
            "trades": [],
            "notes": "No candles found in requested period.",
        }

    # 3) Helper to slice candles up to a given cutoff date
    def _slice_up_to(candles: List[Dict], dates: List[Optional[date]], cutoff: date) -> List[Dict]:
        out: List[Dict] = []
        for c, d in zip(candles, dates):
            if d is None:
                continue
            if d <= cutoff:
                out.append(c)
        return out

    trades: List[Dict] = []
    open_trade: Optional[Dict] = None

    # Confluence thresholds based on strategy mode
    # Standard mode: need 4+ confluence factors
    # Aggressive mode: need 3+ confluence factors
    min_trade_conf = 4 if SIGNAL_MODE == "standard" else 3

    # 4) Main backtest loop (one pass through selected Daily indices)
    for idx in indices:
        c = daily[idx]
        d_i = daily_dates[idx]
        if d_i is None:
            continue

        high = c["high"]
        low = c["low"]

        # ---- 4A) Manage existing open trade (check exit on this bar) ----
        if open_trade is not None and idx > open_trade["entry_index"]:
            closed = _maybe_exit_trade(open_trade, high, low, d_i)
            if closed is not None:
                trades.append(closed)
                open_trade = None
                # Do NOT open a new trade on the same bar after closing
                continue

        # If trade still open, skip new entries
        if open_trade is not None:
            continue

        # ---- 4B) Build top-down slices up to this date ----
        daily_slice = _slice_up_to(daily, daily_dates, d_i)
        if len(daily_slice) < 50:
            # Not enough context
            continue

        weekly_slice = _slice_up_to(weekly, weekly_dates, d_i)
        if not weekly_slice:
            continue

        monthly_slice = _slice_up_to(monthly, monthly_dates, d_i)
        h4_slice = _slice_up_to(h4, h4_dates, d_i)

        # ---- 4C) HTF bias & direction (same as scan_single_asset) ----
        mn_trend = _infer_trend(monthly_slice) if monthly_slice else "mixed"
        wk_trend = _infer_trend(weekly_slice) if weekly_slice else "mixed"
        d_trend = _infer_trend(daily_slice) if daily_slice else "mixed"

        direction, _, _ = _pick_direction_from_bias(mn_trend, wk_trend, d_trend)

        # ---- 4D) Confluence flags & trade levels (current strategy logic via adapter) ----
        flags, notes, trade_levels = _strategy_compute_confluence_flags(
            monthly_slice,
            weekly_slice,
            daily_slice,
            h4_slice,
            direction,
        )

        (
            entry,
            sl,
            tp1,
            tp2,
            tp3,
            tp4,
            tp5,
        ) = trade_levels


        confluence_score = sum(1 for v in flags.values() if v)

        # Determine trade status based on confluence
        # Active: Need confirmation + R/R + enough confluence
        # In-progress: Good setup waiting for 4H confirmation
        if flags.get("confirmation") and confluence_score >= min_trade_conf and flags.get("rr"):
            status = "active"
        elif (
            confluence_score >= min_trade_conf - 1
            and flags.get("location")
            and (flags.get("fib") or flags.get("liquidity"))
        ):
            status = "in_progress"
        else:
            status = "scan_only"

        # For backtest we only open trades on fully ACTIVE signals
        if status != "active":
            continue

        if entry is None or sl is None or tp1 is None:
            continue

        risk = abs(entry - sl)
        if risk <= 0:
            continue

        open_trade = {
            "asset": asset,
            "direction": direction,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "tp4": tp4,
            "tp5": tp5,
            "risk": risk,
            "entry_date": d_i,
            "entry_index": idx,
        }

    # We ignore any still-open trade at the end (not closed yet)

    # 5) Aggregate stats
    total_trades = len(trades)
    if total_trades > 0:
        wins = sum(1 for t in trades if t["rr"] > 0)
        win_rate = wins / total_trades * 100.0
        total_rr = sum(t["rr"] for t in trades)
        net_return_pct = total_rr * 1.0  # 1R = 1% risk
    else:
        win_rate = 0.0
        net_return_pct = 0.0

    notes = (
        "Backtest uses the current Daily-based Blueprint confluence logic "
        "(HTF bias, location, Fib, liquidity, structure, 4H confirmation, R/R), "
        "via the same internal function as /scan. Trades are triggered only on "
        "fully ACTIVE signals, with intrabar execution approximated using Daily high/low."
    )

    return {
        "asset": asset,
        "period": period_label,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "net_return_pct": net_return_pct,
        "trades": trades,
        "notes": notes,
    }
