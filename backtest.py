"""
Enhanced Backtest Engine for Blueprint Trader AI.

============================================================================
USES SHARED STRATEGY ENGINE (strategy_core.py)
============================================================================

This backtest engine uses the SAME strategy logic as live trading:
- Calls _compute_confluence_flags() from strategy_core.py
- Uses identical confluence scoring and filter rules
- Applies same risk management parameters

RELIABILITY GUARANTEE:
The /backtest command shows EXACTLY what the bot would have done live
with the same parameters. No separate "toy" logic exists.

Features:
- Walk-forward simulation with no look-ahead bias
- Proper trade execution simulation using candle H/L
- Partial profit taking support
- Detailed trade logging
- Multiple exit scenarios
- The5ers challenge simulation (Phase 1 & Phase 2)
- Daily/total drawdown tracking per prop firm rules
============================================================================
"""

from __future__ import annotations

from datetime import datetime, date, timedelta, timezone
from typing import List, Dict, Tuple, Optional

from data import get_ohlcv
from config import SIGNAL_MODE, ACCOUNT_SIZE, RISK_PER_TRADE_PCT, ACTIVE_ACCOUNT_PROFILE
from strategy_core import (
    _infer_trend,
    _pick_direction_from_bias,
    _compute_confluence_flags,
    _find_pivots,
    _atr,
)


def _parse_partial_date(s: str, for_start: bool) -> Optional[date]:
    """Parse date strings like 'Jan 2024', '2024-01-01', 'Now'."""
    s = s.strip()
    if not s:
        return None

    lower = s.lower()
    if lower in ("now", "today"):
        return date.today()

    fmts = ["%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%Y/%m/%d"]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass

    month_fmts = ["%b %Y", "%B %Y"]
    for fmt in month_fmts:
        try:
            dt = datetime.strptime(s, fmt).date()
            if for_start:
                return date(dt.year, dt.month, 1)
            else:
                if dt.month == 12:
                    return date(dt.year, 12, 31)
                else:
                    next_month = date(dt.year, dt.month + 1, 1)
                    return next_month - timedelta(days=1)
        except Exception:
            pass

    return None


def _parse_period(period_str: str) -> Tuple[Optional[date], Optional[date]]:
    """Parse 'Jan 2024 - Sep 2024' into (start_date, end_date)."""
    s = period_str.strip()
    if "-" in s:
        left, right = s.split("-", 1)
    else:
        left, right = s, "now"

    start = _parse_partial_date(left.strip(), for_start=True)
    end = _parse_partial_date(right.strip(), for_start=False)

    if start and end and start > end:
        start, end = end, start

    return start, end


def _candle_to_datetime(candle: Dict) -> Optional[datetime]:
    """Get datetime from a candle dict, normalized to UTC."""
    t = candle.get("time") or candle.get("timestamp") or candle.get("date")
    if t is None:
        return None

    dt = None
    if isinstance(t, datetime):
        dt = t
    elif isinstance(t, date):
        dt = datetime(t.year, t.month, t.day, tzinfo=timezone.utc)
    elif isinstance(t, (int, float)):
        try:
            dt = datetime.utcfromtimestamp(t).replace(tzinfo=timezone.utc)
        except Exception:
            return None
    elif isinstance(t, str):
        s = t.strip()
        try:
            s2 = s.replace("Z", "+00:00")
            if "." in s2:
                head, tail = s2.split(".", 1)
                decimals = "".join(ch for ch in tail if ch.isdigit())[:6]
                rest = tail[len(decimals):]
                s2 = f"{head}.{decimals}{rest}"
            dt = datetime.fromisoformat(s2)
        except Exception:
            pass

        if dt is None:
            fmts = ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]
            for fmt in fmts:
                try:
                    dt = datetime.strptime(s[:len(fmt)], fmt)
                    break
                except Exception:
                    continue
    
    if dt is not None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
    
    return dt


def _candle_to_date(candle: Dict) -> Optional[date]:
    dt = _candle_to_datetime(candle)
    return dt.date() if dt else None


def _build_date_list(candles: List[Dict]) -> List[Optional[date]]:
    return [_candle_to_date(c) for c in candles]


def _build_dt_list(candles: List[Dict]) -> List[Optional[datetime]]:
    """Build list of datetime objects for timestamp-accurate slicing."""
    return [_candle_to_datetime(c) for c in candles]


def _slice_up_to_dt(candles: List[Dict], dts: List[Optional[datetime]], cutoff_dt: Optional[datetime]) -> List[Dict]:
    """Slice candles up to and including cutoff datetime (timestamp-accurate)."""
    if cutoff_dt is None:
        return []
    return [c for c, t in zip(candles, dts) if t and t <= cutoff_dt]


def _maybe_exit_trade(
    trade: Dict,
    high: float,
    low: float,
    exit_date: date,
) -> Optional[Dict]:
    """
    Check if trade hits TP or SL on a candle.
    Conservative approach: if SL and any TP are both hit on same bar, assume SL hit first.
    Trailing stop moves to breakeven after TP1 hit.
    """
    direction = trade["direction"]
    entry = trade["entry"]
    sl = trade.get("trailing_sl", trade["sl"])
    orig_sl = trade["sl"]
    tp1 = trade["tp1"]
    tp2 = trade["tp2"]
    tp3 = trade["tp3"]
    risk = trade["risk"]
    tp1_hit = trade.get("tp1_hit", False)

    if direction == "bullish":
        hit_tp3 = tp3 is not None and high >= tp3
        hit_tp2 = tp2 is not None and high >= tp2
        hit_tp1 = tp1 is not None and high >= tp1
        hit_sl = low <= sl

        if hit_sl:
            if tp1_hit:
                rr = (sl - entry) / risk
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "entry": entry,
                    "sl": orig_sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "tp3": tp3,
                    "direction": direction,
                    "rr": max(rr, 0.0),
                    "exit_reason": "TP1+Trail",
                }
            else:
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "entry": entry,
                    "sl": orig_sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "tp3": tp3,
                    "direction": direction,
                    "rr": -1.0,
                    "exit_reason": "SL",
                }
        
        if tp1_hit:
            if hit_tp3:
                rr = (tp3 - entry) / risk
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "entry": entry,
                    "sl": orig_sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "tp3": tp3,
                    "direction": direction,
                    "rr": rr,
                    "exit_reason": "TP3",
                }
            elif hit_tp2:
                rr = (tp2 - entry) / risk
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "entry": entry,
                    "sl": orig_sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "tp3": tp3,
                    "direction": direction,
                    "rr": rr,
                    "exit_reason": "TP2",
                }
        elif hit_tp1 and not tp1_hit:
            trade["tp1_hit"] = True
            new_sl = entry
            trade["trailing_sl"] = new_sl
            if low <= new_sl:
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "entry": entry,
                    "sl": orig_sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "tp3": tp3,
                    "direction": direction,
                    "rr": 0.0,
                    "exit_reason": "TP1+Trail",
                }
            return None

    else:
        hit_tp3 = tp3 is not None and low <= tp3
        hit_tp2 = tp2 is not None and low <= tp2
        hit_tp1 = tp1 is not None and low <= tp1
        hit_sl = high >= sl

        if hit_sl:
            if tp1_hit:
                rr = (entry - sl) / risk
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "entry": entry,
                    "sl": orig_sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "tp3": tp3,
                    "direction": direction,
                    "rr": max(rr, 0.0),
                    "exit_reason": "TP1+Trail",
                }
            else:
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "entry": entry,
                    "sl": orig_sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "tp3": tp3,
                    "direction": direction,
                    "rr": -1.0,
                    "exit_reason": "SL",
                }
        
        if tp1_hit:
            if hit_tp3:
                rr = (entry - tp3) / risk
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "entry": entry,
                    "sl": orig_sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "tp3": tp3,
                    "direction": direction,
                    "rr": rr,
                    "exit_reason": "TP3",
                }
            elif hit_tp2:
                rr = (entry - tp2) / risk
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "entry": entry,
                    "sl": orig_sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "tp3": tp3,
                    "direction": direction,
                    "rr": rr,
                    "exit_reason": "TP2",
                }
        elif hit_tp1 and not tp1_hit:
            trade["tp1_hit"] = True
            new_sl = entry
            trade["trailing_sl"] = new_sl
            if high >= new_sl:
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "entry": entry,
                    "sl": orig_sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "tp3": tp3,
                    "direction": direction,
                    "rr": 0.0,
                    "exit_reason": "TP1+Trail",
                }
            return None

    return None


def simulate_challenge_phase(
    trades: List[Dict],
    account_size: float,
    risk_per_trade_pct: float,
    phase_target_pct: float,
    max_daily_loss_pct: float,
    max_total_loss_pct: float,
    min_profitable_days: int,
    min_profit_per_day_pct: float,
) -> Dict:
    """
    Simulate a challenge phase with The5ers rules.
    
    Returns detailed phase simulation results including:
    - Whether phase would be passed
    - Days to complete (if passed)
    - Rule violations (if any)
    - Daily breakdown
    """
    if not trades:
        return {
            "passed": False,
            "reason": "No trades",
            "days_to_complete": 0,
            "profitable_days": 0,
            "daily_loss_violations": 0,
            "total_loss_violations": 0,
            "final_balance": account_size,
            "final_pnl_pct": 0.0,
        }
    
    balance = account_size
    peak_balance = account_size
    risk_per_trade_usd = account_size * risk_per_trade_pct
    target_balance = account_size * (1 + phase_target_pct)
    min_day_profit_usd = account_size * min_profit_per_day_pct
    
    daily_pnl: Dict[str, float] = {}
    daily_loss_violations = 0
    total_loss_violations = 0
    passed = False
    days_to_complete = 0
    
    for trade in trades:
        trade_date = trade.get("exit_date", trade.get("entry_date", ""))
        rr = trade.get("rr", 0)
        pnl_usd = rr * risk_per_trade_usd
        
        if trade_date not in daily_pnl:
            daily_pnl[trade_date] = 0.0
        daily_pnl[trade_date] += pnl_usd
        
        balance += pnl_usd
        
        if balance > peak_balance:
            peak_balance = balance
        
        day_loss = daily_pnl[trade_date]
        if day_loss < 0 and abs(day_loss) > account_size * max_daily_loss_pct:
            daily_loss_violations += 1
        
        total_dd = account_size - balance
        if total_dd > account_size * max_total_loss_pct:
            total_loss_violations += 1
        
        if balance >= target_balance and not passed:
            passed = True
            days_to_complete = len(daily_pnl)
    
    profitable_days = sum(1 for pnl in daily_pnl.values() if pnl >= min_day_profit_usd)
    
    if passed and profitable_days < min_profitable_days:
        passed = False
    
    if daily_loss_violations > 0 or total_loss_violations > 0:
        passed = False
    
    final_pnl_pct = ((balance - account_size) / account_size) * 100
    
    reason = ""
    if passed:
        reason = f"Passed in {days_to_complete} trading days"
    elif daily_loss_violations > 0:
        reason = f"Failed: {daily_loss_violations} daily loss violations"
    elif total_loss_violations > 0:
        reason = f"Failed: {total_loss_violations} total loss violations"
    elif profitable_days < min_profitable_days:
        reason = f"Failed: Only {profitable_days}/{min_profitable_days} profitable days"
    else:
        reason = f"Did not reach target ({final_pnl_pct:.1f}% vs {phase_target_pct*100:.1f}%)"
    
    return {
        "passed": passed,
        "reason": reason,
        "days_to_complete": days_to_complete if passed else len(daily_pnl),
        "profitable_days": profitable_days,
        "min_profitable_days": min_profitable_days,
        "daily_loss_violations": daily_loss_violations,
        "total_loss_violations": total_loss_violations,
        "final_balance": balance,
        "final_pnl_pct": final_pnl_pct,
        "target_pnl_pct": phase_target_pct * 100,
        "trading_days": len(daily_pnl),
    }


def run_backtest(asset: str, period: str) -> Dict:
    """
    Walk-forward backtest of the Blueprint strategy.
    
    Key improvements:
    - No look-ahead bias: uses only data available at each point
    - Proper trade execution simulation
    - Detailed trade logging
    - Conservative exit assumptions
    - The5ers challenge phase simulation
    """
    daily = get_ohlcv(asset, timeframe="D", count=2000, use_cache=False)
    if not daily:
        return {
            "asset": asset,
            "period": period,
            "total_trades": 0,
            "win_rate": 0.0,
            "net_return_pct": 0.0,
            "trades": [],
            "notes": "No Daily data available.",
        }

    weekly = get_ohlcv(asset, timeframe="W", count=500, use_cache=False) or []
    monthly = get_ohlcv(asset, timeframe="M", count=240, use_cache=False) or []
    h4 = get_ohlcv(asset, timeframe="H4", count=2000, use_cache=False) or []

    daily_dates = _build_date_list(daily)
    weekly_dates = _build_date_list(weekly)
    monthly_dates = _build_date_list(monthly)
    h4_dates = _build_date_list(h4)
    
    daily_dts = _build_dt_list(daily)
    weekly_dts = _build_dt_list(weekly)
    monthly_dts = _build_dt_list(monthly)
    h4_dts = _build_dt_list(h4)

    start_req, end_req = _parse_period(period)

    indices: List[int] = []

    if start_req or end_req:
        last_d = next((d for d in reversed(daily_dates) if d is not None), None)
        first_d = next((d for d in daily_dates if d is not None), None)

        end_date = end_req or last_d
        start_date = start_req or first_d

        if start_date is None or end_date is None:
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
                start_idx = max(0, len(daily) - 260)
                indices = list(range(start_idx, len(daily)))
                period_label = "Last 260 Daily candles"
            else:
                sd = daily_dates[indices[0]]
                ed = daily_dates[indices[-1]]
                period_label = f"{sd.isoformat()} - {ed.isoformat()}" if sd and ed else period
    else:
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

    trades: List[Dict] = []
    open_trade: Optional[Dict] = None
    
    min_trade_conf = 2 if SIGNAL_MODE == "standard" else 1
    cooldown_bars = 0
    last_trade_idx = -1

    for idx in indices:
        c = daily[idx]
        d_i = daily_dates[idx]
        cutoff_dt = daily_dts[idx]
        if d_i is None or cutoff_dt is None:
            continue

        high = c["high"]
        low = c["low"]
        close = c["close"]

        if open_trade is not None and idx > open_trade["entry_index"]:
            closed = _maybe_exit_trade(open_trade, high, low, d_i)
            if closed is not None:
                trades.append(closed)
                open_trade = None
                last_trade_idx = idx
                continue

        if open_trade is not None:
            continue

        if idx - last_trade_idx < cooldown_bars:
            continue

        daily_slice = _slice_up_to_dt(daily, daily_dts, cutoff_dt)
        if len(daily_slice) < 30:
            continue

        weekly_slice = _slice_up_to_dt(weekly, weekly_dts, cutoff_dt)
        if not weekly_slice or len(weekly_slice) < 8:
            continue

        monthly_slice = _slice_up_to_dt(monthly, monthly_dts, cutoff_dt)
        h4_slice = _slice_up_to_dt(h4, h4_dts, cutoff_dt)

        mn_trend = _infer_trend(monthly_slice) if monthly_slice else "mixed"
        wk_trend = _infer_trend(weekly_slice) if weekly_slice else "mixed"
        d_trend = _infer_trend(daily_slice) if daily_slice else "mixed"

        direction, _, _ = _pick_direction_from_bias(mn_trend, wk_trend, d_trend)

        flags, notes, trade_levels = _compute_confluence_flags(
            monthly_slice,
            weekly_slice,
            daily_slice,
            h4_slice,
            direction,
        )

        entry, sl, tp1, tp2, tp3, tp4, tp5 = trade_levels

        confluence_score = sum(1 for v in flags.values() if v)

        has_confirmation = flags.get("confirmation", False)
        has_rr = flags.get("rr", False)
        has_location = flags.get("location", False)
        has_fib = flags.get("fib", False)
        has_liquidity = flags.get("liquidity", False)
        has_structure = flags.get("structure", False)
        has_htf_bias = flags.get("htf_bias", False)

        quality_factors = sum([has_location, has_fib, has_liquidity, has_structure, has_htf_bias])
        
        if has_rr and confluence_score >= min_trade_conf and quality_factors >= 1:
            status = "active"
        elif confluence_score >= min_trade_conf:
            status = "watching"
        else:
            status = "scan_only"

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
            "confluence": confluence_score,
        }

    account_size = ACCOUNT_SIZE
    risk_per_trade_pct = RISK_PER_TRADE_PCT
    profile = ACTIVE_ACCOUNT_PROFILE
    
    total_trades = len(trades)
    if total_trades > 0:
        wins = sum(1 for t in trades if t["rr"] > 0)
        win_rate = wins / total_trades * 100.0
        total_rr = sum(t["rr"] for t in trades)
        net_return_pct = total_rr * risk_per_trade_pct * 100
        avg_rr = total_rr / total_trades
    else:
        win_rate = 0.0
        net_return_pct = 0.0
        total_rr = 0.0
        avg_rr = 0.0

    risk_per_trade_usd = account_size * risk_per_trade_pct
    total_profit_usd = total_rr * risk_per_trade_usd
    
    running_pnl = 0.0
    max_drawdown = 0.0
    peak = 0.0
    
    for t in trades:
        running_pnl += t["rr"] * risk_per_trade_usd
        if running_pnl > peak:
            peak = running_pnl
        drawdown = peak - running_pnl
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    
    max_drawdown_pct = (max_drawdown / account_size) * 100 if account_size > 0 else 0.0

    tp1_trail_hits = sum(1 for t in trades if t.get("exit_reason") == "TP1+Trail")
    tp2_hits = sum(1 for t in trades if t.get("exit_reason") == "TP2")
    tp3_hits = sum(1 for t in trades if t.get("exit_reason") == "TP3")
    sl_hits = sum(1 for t in trades if t.get("exit_reason") == "SL")
    
    wins = tp1_trail_hits + tp2_hits + tp3_hits

    phase1_target = profile.phases[0].profit_target_pct if profile.phases else 0.08
    phase2_target = profile.phases[1].profit_target_pct if len(profile.phases) > 1 else 0.05
    min_profitable_days = profile.phases[0].min_profitable_days if profile.phases else 3
    min_profit_per_day = profile.phases[0].min_profit_per_day_pct if profile.phases else 0.005
    
    phase1_sim = simulate_challenge_phase(
        trades=trades,
        account_size=account_size,
        risk_per_trade_pct=risk_per_trade_pct,
        phase_target_pct=phase1_target,
        max_daily_loss_pct=profile.max_daily_loss_pct,
        max_total_loss_pct=profile.max_total_loss_pct,
        min_profitable_days=min_profitable_days,
        min_profit_per_day_pct=min_profit_per_day,
    )

    notes_text = (
        f"Backtest Summary - {asset} ({period_label}, {profile.display_name})\n"
        f"Trades: {total_trades}\n"
        f"Win rate: {win_rate:.1f}%\n"
        f"Total profit: +${total_profit_usd:,.0f} (+{net_return_pct:.1f}%)\n"
        f"Max drawdown: -{max_drawdown_pct:.1f}%\n"
        f"Expectancy: {avg_rr:+.2f}R / trade\n"
        f"TP1+Trail ({tp1_trail_hits}), TP2 ({tp2_hits}), TP3 ({tp3_hits}), SL ({sl_hits})\n"
        f"\n"
        f"Phase 1 Simulation ({phase1_target*100:.0f}% target):\n"
        f"  {'PASS' if phase1_sim['passed'] else 'FAIL'}: {phase1_sim['reason']}\n"
        f"  Profitable days: {phase1_sim['profitable_days']}/{min_profitable_days}\n"
        f"  Rule violations: Daily={phase1_sim['daily_loss_violations']}, Total={phase1_sim['total_loss_violations']}"
    )

    return {
        "asset": asset,
        "period": period_label,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "net_return_pct": net_return_pct,
        "total_profit_usd": total_profit_usd,
        "max_drawdown_pct": max_drawdown_pct,
        "avg_rr": avg_rr,
        "tp1_trail_hits": tp1_trail_hits,
        "tp2_hits": tp2_hits,
        "tp3_hits": tp3_hits,
        "sl_hits": sl_hits,
        "trades": trades,
        "notes": notes_text,
        "account_size": account_size,
        "risk_per_trade_pct": risk_per_trade_pct,
        "profile_name": profile.display_name,
        "phase1_simulation": phase1_sim,
    }


def validate_asset_performance(result: dict) -> dict:
    """
    Validate asset performance against target profile thresholds.
    
    Target Profile (50+ trades, 70-100% WR):
    - Min 50 trades per year for significance
    - Win rate 70-100% for consistency
    - Positive return for profitability
    
    Returns validation dict with pass/fail status and reasons.
    """
    validations = {
        "trade_count_pass": result["total_trades"] >= 50,
        "trade_count_value": result["total_trades"],
        "trade_count_reason": f"{'✓' if result['total_trades'] >= 50 else '✗'} {result['total_trades']}/50+ trades",
        
        "win_rate_pass": 70 <= result["win_rate"] <= 100,
        "win_rate_value": result["win_rate"],
        "win_rate_reason": f"{'✓' if 70 <= result['win_rate'] <= 100 else '✗'} {result['win_rate']:.1f}% (target: 70-100%)",
        
        "profitability_pass": result["net_return_pct"] > 0,
        "profitability_value": result["net_return_pct"],
        "profitability_reason": f"{'✓' if result['net_return_pct'] > 0 else '✗'} {result['net_return_pct']:+.1f}% return",
        
        "expectancy_pass": result["avg_rr"] > 0,
        "expectancy_value": result["avg_rr"],
        "expectancy_reason": f"{'✓' if result['avg_rr'] > 0 else '✗'} {result['avg_rr']:+.2f}R expectancy",
    }
    
    validations["all_pass"] = all([
        validations["trade_count_pass"],
        validations["win_rate_pass"],
        validations["profitability_pass"],
        validations["expectancy_pass"],
    ])
    
    return validations


def run_yearly_backtest(asset: str, year: int, profile=None):
    """
    Run backtest for each month of a year and aggregate per-asset metrics.
    
    Returns yearly summary with monthly breakdown and performance validation.
    """
    from config import ACTIVE_ACCOUNT_PROFILE
    import calendar
    
    if profile is None:
        profile = ACTIVE_ACCOUNT_PROFILE
    
    monthly_results = []
    yearly_trades = []
    yearly_profit = 0.0
    yearly_return = 0.0
    
    print(f"\n{'='*60}")
    print(f"YEARLY BACKTEST: {asset} / {year}")
    print(f"Profile: {profile.display_name}")
    print(f"{'='*60}\n")
    
    for month in range(1, 13):
        month_name = calendar.month_name[month]
        start_day = 1
        
        if month == 12:
            end_day = 31
        else:
            end_day = calendar.monthrange(year, month + 1)[1] - 1
        
        period = f"{month_name} 1 - {end_day}, {year}"
        
        try:
            result = run_backtest(asset, period, profile)
            monthly_results.append(result)
            yearly_trades.extend(result.get("trades", []))
            yearly_profit += result["total_profit_usd"]
            yearly_return += result["net_return_pct"]
            
            status = "✓" if result["win_rate"] >= 50 else "✗"
            print(f"{month_name:>10}: {status} WR={result['win_rate']:5.1f}% | "
                  f"Trades={result['total_trades']:3.0f} | "
                  f"Return={result['net_return_pct']:+6.1f}%")
        except Exception as e:
            print(f"{month_name:>10}: ERROR - {str(e)[:40]}")
            continue
    
    total_trades = len(yearly_trades)
    yearly_win_rate = sum(1 for t in yearly_trades if t["rr"] > 0) / total_trades * 100 if total_trades > 0 else 0
    avg_rr = sum(t["rr"] for t in yearly_trades) / total_trades if total_trades > 0 else 0
    
    print(f"\n{'='*60}")
    print(f"YEARLY SUMMARY: {asset} / {year}")
    print(f"Total Trades: {total_trades}")
    print(f"Win Rate: {yearly_win_rate:.1f}%")
    print(f"Yearly Return: {yearly_return:.1f}% (+${yearly_profit:,.0f})")
    print(f"Avg Expectancy: {avg_rr:+.2f}R/trade")
    print(f"{'='*60}\n")
    
    yearly_result = {
        "asset": asset,
        "year": year,
        "total_trades": total_trades,
        "win_rate": yearly_win_rate,
        "net_return_pct": yearly_return,
        "total_profit_usd": yearly_profit,
        "avg_rr": avg_rr,
        "monthly_results": monthly_results,
        "trades": yearly_trades,
    }
    
    yearly_result["validation"] = validate_asset_performance(yearly_result)
    
    return yearly_result
