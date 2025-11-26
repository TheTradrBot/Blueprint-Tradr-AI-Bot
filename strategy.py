from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict

from data import get_ohlcv
from config import (
    FOREX_PAIRS,
    METALS,
    INDICES,
    ENERGIES,
    CRYPTO_ASSETS,
    SIGNAL_MODE,
)


@dataclass
class ScanResult:
    symbol: str
    direction: str
    confluence_score: int
    htf_bias: str
    location_note: str
    fib_note: str
    liquidity_note: str
    structure_note: str
    confirmation_note: str
    rr_note: str
    summary_reason: str
    status: str = "scan_only"
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    tp4: Optional[float] = None
    tp5: Optional[float] = None
    setup_type: str = ""
    what_to_look_for: str = ""


def _safe_min_max(candles: List[Dict]) -> Tuple[float, float]:
    lows = [c["low"] for c in candles]
    highs = [c["high"] for c in candles]
    if not lows or not highs:
        return float("nan"), float("nan")
    return min(lows), max(highs)


def _percent_distance(a: float, b: float) -> float:
    if a == 0:
        return float("inf")
    return abs(b - a) / abs(a) * 100.0


def _find_pivots(
    candles: List[Dict],
    lookback: int = 2,
) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    """Find swing highs/lows using a symmetric lookback window."""
    highs: List[Tuple[int, float]] = []
    lows: List[Tuple[int, float]] = []

    n = len(candles)
    if n < 2 * lookback + 1:
        return highs, lows

    for i in range(lookback, n - lookback):
        hi = candles[i]["high"]
        lo = candles[i]["low"]

        if all(hi > candles[j]["high"] for j in range(i - lookback, i + lookback + 1) if j != i):
            highs.append((i, hi))

        if all(lo < candles[j]["low"] for j in range(i - lookback, i + lookback + 1) if j != i):
            lows.append((i, lo))

    return highs, lows


def _find_swings(candles: List[Dict], left: int = 3, right: int = 2) -> Tuple[List[int], List[int]]:
    """Find swing high/low indices with asymmetric lookback."""
    swing_highs: List[int] = []
    swing_lows: List[int] = []
    n = len(candles)
    
    if n < left + right + 1:
        return swing_highs, swing_lows
    
    for i in range(left, n - right):
        is_swing_high = True
        is_swing_low = True
        
        for j in range(i - left, i + right + 1):
            if j == i:
                continue
            if candles[j]["high"] >= candles[i]["high"]:
                is_swing_high = False
            if candles[j]["low"] <= candles[i]["low"]:
                is_swing_low = False
        
        if is_swing_high:
            swing_highs.append(i)
        if is_swing_low:
            swing_lows.append(i)
    
    return swing_highs, swing_lows


def _infer_trend(candles: List[Dict]) -> str:
    """HH/HL vs LH/LL based trend inference using pivots."""
    if len(candles) < 10:
        return "mixed"
    
    highs, lows = _find_pivots(candles, lookback=3)
    
    if len(highs) < 2 or len(lows) < 2:
        if len(candles) < 5:
            return "mixed"
        if candles[-1]["close"] > candles[-5]["close"]:
            return "bullish"
        if candles[-1]["close"] < candles[-5]["close"]:
            return "bearish"
        return "mixed"

    last_highs = highs[-3:] if len(highs) >= 3 else highs[-2:]
    last_lows = lows[-3:] if len(lows) >= 3 else lows[-2:]

    hh_count = sum(1 for i in range(1, len(last_highs)) if last_highs[i][1] > last_highs[i-1][1])
    lh_count = sum(1 for i in range(1, len(last_highs)) if last_highs[i][1] < last_highs[i-1][1])
    hl_count = sum(1 for i in range(1, len(last_lows)) if last_lows[i][1] > last_lows[i-1][1])
    ll_count = sum(1 for i in range(1, len(last_lows)) if last_lows[i][1] < last_lows[i-1][1])

    bullish_score = hh_count + hl_count
    bearish_score = lh_count + ll_count

    if bullish_score > bearish_score and bullish_score >= 2:
        return "bullish"
    if bearish_score > bullish_score and bearish_score >= 2:
        return "bearish"
    return "mixed"


def _infer_daily_trend(daily_candles: List[Dict]) -> str:
    return _infer_trend(daily_candles)


def _range_position(
    candles: List[Dict],
    price: float,
) -> Tuple[Tuple[float, float], str, bool]:
    """Compute [low, high] of a window and whether price is at edges."""
    r_low, r_high = _safe_min_max(candles)
    if r_low != r_low or r_high != r_high:
        return (r_low, r_high), "range: N/A", False

    span = r_high - r_low
    if span <= 0:
        return (r_low, r_high), f"range: {r_low:.5f}–{r_high:.5f}", False

    lower_band = r_low + span * 0.30
    upper_band = r_low + span * 0.70

    if price <= lower_band:
        note = f"price in lower edge of range ({r_low:.5f}–{r_high:.5f})"
        return (r_low, r_high), note, True
    elif price >= upper_band:
        note = f"price in upper edge of range ({r_low:.5f}–{r_high:.5f})"
        return (r_low, r_high), note, True
    else:
        note = f"price mid-range ({r_low:.5f}–{r_high:.5f})"
        return (r_low, r_high), note, False


def _cluster_prices(prices: List[float], tolerance_pct: float = 0.35) -> List[Tuple[float, int]]:
    """Cluster nearby prices into levels and count taps."""
    clusters: List[dict] = []
    for p in sorted(prices):
        placed = False
        for cl in clusters:
            if _percent_distance(cl["price"], p) <= tolerance_pct:
                cl["sum"] += p
                cl["count"] += 1
                cl["price"] = cl["sum"] / cl["count"]
                placed = True
                break
        if not placed:
            clusters.append({"price": p, "sum": p, "count": 1})
    return [(cl["price"], cl["count"]) for cl in clusters]


def _build_sr_levels(candles: List[Dict], tolerance_pct: float = 0.35) -> List[Dict]:
    """Build S/R levels from pivots and cluster them."""
    highs, lows = _find_pivots(candles, lookback=3)
    prices = [p for _, p in highs] + [p for _, p in lows]
    if not prices:
        return []

    clustered = _cluster_prices(prices, tolerance_pct)
    levels: List[Dict] = []
    for level_price, taps in clustered:
        if taps >= 4:
            tier = 1
        elif taps >= 2:
            tier = 2
        else:
            tier = 3
        levels.append({"price": level_price, "taps": taps, "tier": tier})
    return levels


def _nearest_sr_level(levels: List[Dict], price: float) -> Optional[Dict]:
    """Pick nearest S/R level to price."""
    if not levels or price != price:
        return None
    best = None
    best_dist = float("inf")
    for lvl in levels:
        dist = _percent_distance(price, lvl["price"])
        if dist < best_dist:
            best_dist = dist
            best = lvl
    if best is None:
        return None
    level_copy = dict(best)
    level_copy["dist_pct"] = best_dist
    return level_copy


def _approx_near_zone(
    candles: List[Dict],
    price: float,
    zone_type: str,
    lookback: int = 80,
) -> Optional[Tuple[float, float, float]]:
    """Approximate nearest supply/demand zone."""
    if not candles or price != price:
        return None

    subset = candles[-min(len(candles), lookback):]
    candidates: List[Tuple[float, float, float]] = []

    for c in subset:
        low = c["low"]
        high = c["high"]
        mid = (low + high) / 2.0

        if zone_type == "supply":
            if mid <= price:
                continue
            dist_pct = _percent_distance(price, mid)
        else:
            if mid >= price:
                continue
            dist_pct = _percent_distance(price, mid)

        candidates.append((dist_pct, low, high))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])
    dist_pct, z_low, z_high = candidates[0]
    return z_low, z_high, dist_pct


def _pick_direction_from_bias(
    monthly_trend: str,
    weekly_trend: str,
    daily_trend: str,
) -> Tuple[str, str, bool]:
    """Decide trade direction from HTF bias."""
    note_parts: List[str] = []
    strong = False
    direction = "neutral"

    if weekly_trend in ("bullish", "bearish"):
        direction = weekly_trend
        
        if weekly_trend == daily_trend:
            strong = True
            if monthly_trend == weekly_trend:
                note_parts.append(
                    f"HTF trend alignment: Monthly={monthly_trend}, Weekly={weekly_trend}, Daily={daily_trend}."
                )
            else:
                note_parts.append(
                    f"HTF reversal bias: Monthly={monthly_trend}, Weekly={weekly_trend}, Daily={daily_trend}."
                )
        elif daily_trend == "mixed":
            strong = True
            note_parts.append(
                f"HTF bias: Weekly={weekly_trend} leading, Daily={daily_trend} (pullback phase)."
            )
        else:
            strong = False
            note_parts.append(
                f"HTF conflict: Weekly={weekly_trend} vs Daily={daily_trend}."
            )
    else:
        if daily_trend in ("bullish", "bearish"):
            direction = daily_trend
            strong = daily_trend == monthly_trend
        else:
            direction = "bullish" if monthly_trend == "bullish" else "bearish" if monthly_trend == "bearish" else "bullish"

        note_parts.append(
            f"HTF bias weak: Monthly={monthly_trend}, Weekly={weekly_trend}, Daily={daily_trend}."
        )
        strong = False

    return direction, " ".join(note_parts), strong


def _location_context(
    monthly_candles: List[Dict],
    weekly_candles: List[Dict],
    daily_candles: List[Dict],
    price: float,
    direction: str,
) -> Tuple[str, bool]:
    """Location check for Blueprint strategy - optimized for more trades."""
    notes: List[str] = []
    location_score = 0

    zone_type = "supply" if direction == "bearish" else "demand"

    (mn_low, mn_high), mn_note, mn_edge = _range_position(monthly_candles, price)
    if mn_edge:
        location_score += 2

    mn_levels = _build_sr_levels(monthly_candles) if monthly_candles else []
    mn_near = _nearest_sr_level(mn_levels, price)
    if mn_near and mn_near["dist_pct"] <= 4.0:
        location_score += 2 if mn_near["dist_pct"] <= 2.5 else 1

    (wk_low, wk_high), wk_note, wk_edge = _range_position(weekly_candles, price)
    if wk_edge:
        location_score += 2

    wk_levels = _build_sr_levels(weekly_candles) if weekly_candles else []
    wk_near = _nearest_sr_level(wk_levels, price)
    if wk_near and wk_near["dist_pct"] <= 3.5:
        location_score += 2 if wk_near["dist_pct"] <= 2.0 else 1

    (d_low, d_high), d_note, d_edge = _range_position(daily_candles, price)
    if d_edge:
        location_score += 1

    d_levels = _build_sr_levels(daily_candles) if daily_candles else []
    d_near = _nearest_sr_level(d_levels, price)
    if d_near and d_near["dist_pct"] <= 2.0:
        location_score += 1

    ok = location_score >= 1
    
    if ok:
        notes.append(f"Location score: {location_score} (price near key levels)")
    else:
        notes.append(f"Location score: {location_score} (weak positioning)")
    
    return " ".join(notes), ok


def _find_last_swing_leg_for_fib(
    candles: List[Dict],
    direction: str,
) -> Optional[Tuple[float, float]]:
    """Find the last impulsive leg for Fib retracement."""
    highs, lows = _find_pivots(candles, lookback=3)
    if not highs or not lows:
        return None

    if direction == "bullish":
        hi_idx, hi_price = highs[-1]
        candidate_lows = [pl for pl in lows if pl[0] < hi_idx]
        if not candidate_lows:
            return None
        lo_idx, lo_price = candidate_lows[-1]
        if lo_price >= hi_price:
            return None
        return lo_price, hi_price
    else:
        lo_idx, lo_price = lows[-1]
        candidate_highs = [ph for ph in highs if ph[0] < lo_idx]
        if not candidate_highs:
            return None
        hi_idx, hi_price = candidate_highs[-1]
        if hi_price <= lo_price:
            return None
        return lo_price, hi_price


def _fib_context(
    weekly_candles: List[Dict],
    daily_candles: List[Dict],
    direction: str,
    price: float,
) -> Tuple[str, bool]:
    """Fibonacci confluence check on Weekly & Daily - optimized for more trades."""
    notes: List[str] = []
    fib_score = 0

    weekly_leg = _find_last_swing_leg_for_fib(weekly_candles, direction) if weekly_candles else None
    if weekly_leg:
        w_low, w_high = weekly_leg
        span = w_high - w_low
        
        if direction == "bullish":
            w_gp_low = w_high - span * 0.886
            w_gp_high = w_high - span * 0.382
        else:
            w_gp_low = w_low + span * 0.382
            w_gp_high = w_low + span * 0.886

        w_in_zone = w_gp_low <= price <= w_gp_high
        
        if w_in_zone:
            fib_score += 3
            notes.append(f"Weekly: price in retracement zone")
        else:
            dist_to_zone = min(abs(price - w_gp_low), abs(price - w_gp_high))
            if dist_to_zone / span < 0.15:
                fib_score += 1
                notes.append(f"Weekly: price near retracement zone")
            else:
                notes.append(f"Weekly: price outside optimal retracement")

    daily_leg = _find_last_swing_leg_for_fib(daily_candles, direction) if daily_candles else None
    if daily_leg:
        d_low, d_high = daily_leg
        span = d_high - d_low
        
        if direction == "bullish":
            d_gp_low = d_high - span * 0.886
            d_gp_high = d_high - span * 0.382
        else:
            d_gp_low = d_low + span * 0.382
            d_gp_high = d_low + span * 0.886

        d_in_zone = d_gp_low <= price <= d_gp_high
        
        if d_in_zone:
            fib_score += 3
            notes.append(f"Daily: price in retracement zone")
        else:
            dist_to_zone = min(abs(price - d_gp_low), abs(price - d_gp_high))
            if span > 0 and dist_to_zone / span < 0.15:
                fib_score += 1
                notes.append(f"Daily: price near retracement zone")
            else:
                notes.append(f"Daily: price outside optimal retracement")

    if not weekly_leg and not daily_leg:
        return "No clear impulse legs for Fibonacci.", False

    fib_ok = fib_score >= 1
    return " ".join(notes), fib_ok


def _daily_liquidity_context(
    daily_candles: List[Dict],
    price: float,
) -> Tuple[str, bool]:
    """Liquidity & liquidity flows check on Daily - optimized for more trades."""
    if not daily_candles or len(daily_candles) < 15:
        return "Insufficient data for liquidity analysis.", False

    notes: List[str] = []
    ok = False

    lows = [c["low"] for c in daily_candles]
    highs = [c["high"] for c in daily_candles]
    low_ext = min(lows)
    high_ext = max(highs)

    sweep_lookback = 12
    history_window = 80
    
    if len(daily_candles) > sweep_lookback:
        for i in range(1, sweep_lookback + 1):
            candle_idx = len(daily_candles) - i
            recent_candle = daily_candles[candle_idx]
            
            start_idx = max(0, candle_idx - history_window)
            prev_candles = daily_candles[start_idx:candle_idx]
            
            if len(prev_candles) < 8:
                continue
                
            prev_lows = [c["low"] for c in prev_candles]
            prev_highs = [c["high"] for c in prev_candles]
            prev_low_ext = min(prev_lows)
            prev_high_ext = max(prev_highs)

            swept_down = recent_candle["low"] < prev_low_ext and recent_candle["close"] > prev_low_ext
            swept_up = recent_candle["high"] > prev_high_ext and recent_candle["close"] < prev_high_ext

            if swept_down:
                notes.append(f"Liquidity sweep below {prev_low_ext:.5f} detected")
                ok = True
                break
            elif swept_up:
                notes.append(f"Liquidity sweep above {prev_high_ext:.5f} detected")
                ok = True
                break

    eq_threshold = 0.003
    recent_lows = [c["low"] for c in daily_candles[-40:]]
    recent_highs = [c["high"] for c in daily_candles[-40:]]
    
    sorted_lows = sorted(set(recent_lows))
    sorted_highs = sorted(set(recent_highs))
    
    for i in range(len(sorted_lows) - 1):
        if sorted_lows[i] > 0 and abs(sorted_lows[i] - sorted_lows[i+1]) / sorted_lows[i] < eq_threshold:
            if _percent_distance(price, sorted_lows[i]) < 2.5:
                notes.append(f"Equal lows near {sorted_lows[i]:.5f}")
                ok = True
                break
    
    for i in range(len(sorted_highs) - 1):
        if sorted_highs[i] > 0 and abs(sorted_highs[i] - sorted_highs[i+1]) / sorted_highs[i] < eq_threshold:
            if _percent_distance(price, sorted_highs[i]) < 2.5:
                notes.append(f"Equal highs near {sorted_highs[i]:.5f}")
                ok = True
                break

    if not ok:
        dist_to_low = _percent_distance(price, low_ext)
        dist_to_high = _percent_distance(price, high_ext)
        if dist_to_low < 5.0 or dist_to_high < 5.0:
            notes.append("Near external liquidity")
            ok = True
        else:
            notes.append("No significant liquidity signals")

    return " ".join(notes), ok


def _structure_context(
    monthly_candles: List[Dict],
    weekly_candles: List[Dict],
    daily_candles: List[Dict],
    direction: str,
) -> Tuple[bool, str]:
    """Evaluate market structure alignment."""
    notes: List[str] = []
    structure_score = 0

    wk_trend = _infer_trend(weekly_candles) if weekly_candles else "mixed"
    d_trend = _infer_trend(daily_candles) if daily_candles else "mixed"

    if direction == "bullish":
        if wk_trend == "bullish":
            structure_score += 2
            notes.append("Weekly structure bullish")
        if d_trend == "bullish":
            structure_score += 2
            notes.append("Daily structure bullish")
        elif d_trend == "mixed":
            structure_score += 1
            notes.append("Daily structure consolidating")
    else:
        if wk_trend == "bearish":
            structure_score += 2
            notes.append("Weekly structure bearish")
        if d_trend == "bearish":
            structure_score += 2
            notes.append("Daily structure bearish")
        elif d_trend == "mixed":
            structure_score += 1
            notes.append("Daily structure consolidating")

    if daily_candles and len(daily_candles) >= 20:
        swing_highs, swing_lows = _find_swings(daily_candles)
        if swing_highs and swing_lows:
            if len(swing_highs) >= 2 and len(swing_lows) >= 2:
                structure_score += 1
                notes.append("Clear swing structure")

    ok = structure_score >= 2
    return ok, " ".join(notes) if notes else "Structure neutral"


def _h4_confirmation(
    h4_candles: List[Dict],
    direction: str,
    daily_candles: Optional[List[Dict]] = None,
) -> Tuple[str, bool]:
    """4H confirmation check with Daily fallback - optimized for higher trade count."""
    candles = h4_candles if h4_candles and len(h4_candles) >= 10 else daily_candles
    tf_label = "4H" if h4_candles and len(h4_candles) >= 10 else "Daily"
    
    if not candles or len(candles) < 10:
        return "Insufficient data for confirmation.", False

    swing_highs, swing_lows = _find_swings(candles, left=2, right=1)
    
    notes: List[str] = []
    confirmation_score = 0

    if direction == "bearish":
        if swing_lows:
            relevant_lows = [idx for idx in swing_lows if idx < len(candles) - 1]
            if relevant_lows:
                key_idx = relevant_lows[-1]
                key_level = candles[key_idx]["low"]
                
                for i in range(1, min(6, len(candles))):
                    if candles[-i]["close"] < key_level:
                        notes.append(f"{tf_label}: BOS down confirmed")
                        confirmation_score += 3
                        break
        
        for i in range(1, min(5, len(candles))):
            candle = candles[-i]
            body = candle["open"] - candle["close"]
            total_range = candle["high"] - candle["low"]
            if total_range > 0 and body > 0:
                body_ratio = body / total_range
                if body_ratio >= 0.45:
                    notes.append(f"{tf_label}: Bearish momentum")
                    confirmation_score += 2
                    break
        
        if len(candles) >= 2:
            curr = candles[-1]
            prev = candles[-2]
            if curr["close"] < curr["open"] and prev["close"] > prev["open"]:
                if curr["open"] >= prev["close"] * 0.998 and curr["close"] <= prev["open"] * 1.002:
                    notes.append(f"{tf_label}: Bearish engulfing")
                    confirmation_score += 2
        
        if len(candles) >= 3:
            last_3_bearish = sum(1 for c in candles[-3:] if c["close"] < c["open"])
            if last_3_bearish >= 2:
                notes.append(f"{tf_label}: Bearish pressure")
                confirmation_score += 1
    else:
        if swing_highs:
            relevant_highs = [idx for idx in swing_highs if idx < len(candles) - 1]
            if relevant_highs:
                key_idx = relevant_highs[-1]
                key_level = candles[key_idx]["high"]
                
                for i in range(1, min(6, len(candles))):
                    if candles[-i]["close"] > key_level:
                        notes.append(f"{tf_label}: BOS up confirmed")
                        confirmation_score += 3
                        break
        
        for i in range(1, min(5, len(candles))):
            candle = candles[-i]
            body = candle["close"] - candle["open"]
            total_range = candle["high"] - candle["low"]
            if total_range > 0 and body > 0:
                body_ratio = body / total_range
                if body_ratio >= 0.45:
                    notes.append(f"{tf_label}: Bullish momentum")
                    confirmation_score += 2
                    break
        
        if len(candles) >= 2:
            curr = candles[-1]
            prev = candles[-2]
            if curr["close"] > curr["open"] and prev["close"] < prev["open"]:
                if curr["open"] <= prev["close"] * 1.002 and curr["close"] >= prev["open"] * 0.998:
                    notes.append(f"{tf_label}: Bullish engulfing")
                    confirmation_score += 2
        
        if len(candles) >= 3:
            last_3_bullish = sum(1 for c in candles[-3:] if c["close"] > c["open"])
            if last_3_bullish >= 2:
                notes.append(f"{tf_label}: Bullish pressure")
                confirmation_score += 1

    confirmed = confirmation_score >= 1
    return " ".join(notes) if notes else f"{tf_label}: No clear confirmation", confirmed


def _atr(candles: List[Dict], period: int = 14) -> float:
    """Simple ATR approximation."""
    if len(candles) < 2:
        return 0.0
    inps = candles[-period:]
    trs = [c["high"] - c["low"] for c in inps]
    if not trs:
        return 0.0
    return sum(trs) / len(trs)


def _find_structure_sl(candles: List[Dict], direction: str, lookback: int = 30) -> Optional[float]:
    """Find structure-based stop loss using recent swing points with wider buffer."""
    if len(candles) < lookback:
        return None
    
    recent = candles[-lookback:]
    swing_highs, swing_lows = _find_swings(recent, left=3, right=1)
    
    if direction == "bullish" and swing_lows:
        lowest_swing = min(recent[i]["low"] for i in swing_lows)
        return lowest_swing
    elif direction == "bearish" and swing_highs:
        highest_swing = max(recent[i]["high"] for i in swing_highs)
        return highest_swing
    
    return None


def _rr_context(
    daily_candles: List[Dict],
    direction: str,
) -> Tuple[str, bool, Optional[float], Optional[float], Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]]:
    """R/R + trade levels with optimized TP/SL placement for higher win rate."""
    if not daily_candles:
        return "R/R: no data.", False, None, None, None, None, None, None, None

    current = daily_candles[-1]["close"]
    atr = _atr(daily_candles, 14)
    
    if atr <= 0:
        return "R/R: ATR too small.", False, None, None, None, None, None, None, None

    leg = _find_last_swing_leg_for_fib(daily_candles, direction)
    structure_sl = _find_structure_sl(daily_candles, direction, lookback=35)

    if leg:
        lo, hi = leg
        span = hi - lo
        if span > 0:
            if direction == "bullish":
                gp_mid = hi - span * 0.618
                entry = current if abs(current - gp_mid) < atr * 0.3 else gp_mid
                
                base_sl = lo - atr * 0.5
                if structure_sl is not None:
                    sl = min(base_sl, structure_sl - atr * 0.4)
                else:
                    sl = base_sl
                
                risk = entry - sl
                
                if risk > 0:
                    tp1 = entry + risk * 0.6
                    tp2 = entry + risk * 1.1
                    tp3 = entry + risk * 1.8
                    tp4 = entry + risk * 2.5
                    tp5 = entry + risk * 3.5
                    
                    note = f"R/R: Entry near {entry:.5f}, SL at {sl:.5f}, TP2 at 1.1R"
                    return note, True, entry, sl, tp1, tp2, tp3, tp4, tp5

            else:
                gp_mid = lo + span * 0.618
                entry = current if abs(current - gp_mid) < atr * 0.3 else gp_mid
                
                base_sl = hi + atr * 0.5
                if structure_sl is not None:
                    sl = max(base_sl, structure_sl + atr * 0.4)
                else:
                    sl = base_sl
                
                risk = sl - entry
                
                if risk > 0:
                    tp1 = entry - risk * 0.6
                    tp2 = entry - risk * 1.1
                    tp3 = entry - risk * 1.8
                    tp4 = entry - risk * 2.5
                    tp5 = entry - risk * 3.5
                    
                    note = f"R/R: Entry near {entry:.5f}, SL at {sl:.5f}, TP2 at 1.1R"
                    return note, True, entry, sl, tp1, tp2, tp3, tp4, tp5

    entry = current
    if direction == "bullish":
        if structure_sl is not None:
            sl = min(entry - atr * 1.5, structure_sl - atr * 0.4)
        else:
            sl = entry - atr * 1.5
        risk = entry - sl
        tp1 = entry + risk * 0.6
        tp2 = entry + risk * 1.1
        tp3 = entry + risk * 1.8
        tp4 = entry + risk * 2.5
        tp5 = entry + risk * 3.5
    else:
        if structure_sl is not None:
            sl = max(entry + atr * 1.5, structure_sl + atr * 0.4)
        else:
            sl = entry + atr * 1.5
        risk = sl - entry
        tp1 = entry - risk * 0.6
        tp2 = entry - risk * 1.1
        tp3 = entry - risk * 1.8
        tp4 = entry - risk * 2.5
        tp5 = entry - risk * 3.5

    note = f"R/R: ATR+structure levels, TP2 at 1.1R"
    return note, True, entry, sl, tp1, tp2, tp3, tp4, tp5


def _compute_confluence_flags(
    monthly_candles: List[Dict],
    weekly_candles: List[Dict],
    daily_candles: List[Dict],
    h4_candles: List[Dict],
    direction: str,
) -> Tuple[Dict[str, bool], Dict[str, str], Tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]]]:
    """Core confluence evaluation."""
    price = daily_candles[-1]["close"] if daily_candles else float("nan")

    mn_trend = _infer_trend(monthly_candles) if monthly_candles else "mixed"
    wk_trend = _infer_trend(weekly_candles) if weekly_candles else "mixed"
    d_trend = _infer_trend(daily_candles) if daily_candles else "mixed"
    _, htf_note_text, htf_ok = _pick_direction_from_bias(mn_trend, wk_trend, d_trend)

    loc_note, loc_ok = _location_context(
        monthly_candles, weekly_candles, daily_candles, price, direction
    )

    fib_note, fib_ok = _fib_context(weekly_candles, daily_candles, direction, price)

    liq_note, liq_ok = _daily_liquidity_context(daily_candles, price)

    struct_ok, struct_note = _structure_context(
        monthly_candles, weekly_candles, daily_candles, direction
    )

    conf_note, conf_ok = _h4_confirmation(h4_candles, direction, daily_candles)

    rr_note, rr_ok, entry, sl, tp1, tp2, tp3, tp4, tp5 = _rr_context(daily_candles, direction)

    flags = {
        "htf_bias": htf_ok,
        "location": loc_ok,
        "fib": fib_ok,
        "liquidity": liq_ok,
        "structure": struct_ok,
        "confirmation": conf_ok,
        "rr": rr_ok,
    }

    notes = {
        "htf_bias": htf_note_text,
        "location": loc_note,
        "fib": fib_note,
        "liquidity": liq_note,
        "structure": struct_note,
        "confirmation": conf_note,
        "rr": rr_note,
    }

    trade_levels = (entry, sl, tp1, tp2, tp3, tp4, tp5)
    return flags, notes, trade_levels


def _generate_setup_info(direction: str, flags: Dict[str, bool], notes: Dict[str, str]) -> Tuple[str, str]:
    """Generate setup type and what to look for."""
    setup_parts = []
    look_for_parts = []
    
    if flags["fib"]:
        setup_parts.append("Fib retracement")
    if flags["liquidity"]:
        setup_parts.append("Liquidity zone")
    if flags["structure"]:
        setup_parts.append("Structure aligned")
    
    setup_type = " + ".join(setup_parts) if setup_parts else "Price action"
    
    if direction == "bullish":
        look_for_parts.append("Bullish rejection from support")
        if not flags["confirmation"]:
            look_for_parts.append("Wait for 4H BOS up or bullish engulfing")
        else:
            look_for_parts.append("Entry trigger confirmed")
    else:
        look_for_parts.append("Bearish rejection from resistance")
        if not flags["confirmation"]:
            look_for_parts.append("Wait for 4H BOS down or bearish engulfing")
        else:
            look_for_parts.append("Entry trigger confirmed")
    
    what_to_look_for = ". ".join(look_for_parts)
    
    return setup_type, what_to_look_for


def scan_single_asset(symbol: str) -> Optional[ScanResult]:
    """Full top-down Blueprint scan for a single asset."""
    monthly = get_ohlcv(symbol, timeframe="M", count=240)
    weekly = get_ohlcv(symbol, timeframe="W", count=520)
    daily = get_ohlcv(symbol, timeframe="D", count=2000)
    h4 = get_ohlcv(symbol, timeframe="H4", count=2000)

    if not daily or not weekly:
        return None

    mn_trend = _infer_trend(monthly) if monthly else "mixed"
    wk_trend = _infer_trend(weekly)
    d_trend = _infer_trend(daily)
    direction, htf_bias_text, _ = _pick_direction_from_bias(mn_trend, wk_trend, d_trend)

    flags, notes, trade_levels = _compute_confluence_flags(
        monthly, weekly, daily, h4, direction
    )
    entry, sl, tp1, tp2, tp3, tp4, tp5 = trade_levels

    confluence_score = sum(1 for v in flags.values() if v)

    min_trade_conf = 4 if SIGNAL_MODE == "standard" else 3

    if flags["confirmation"] and confluence_score >= min_trade_conf and flags["rr"]:
        status = "active"
    elif confluence_score >= min_trade_conf - 1 and (flags["location"] or flags["fib"] or flags["liquidity"]):
        status = "in_progress"
    else:
        status = "scan_only"

    setup_type, what_to_look_for = _generate_setup_info(direction, flags, notes)

    summary = (
        f"{direction.upper()} | {confluence_score}/7 confluence | "
        f"HTF={'Y' if flags['htf_bias'] else 'N'}, "
        f"Loc={'Y' if flags['location'] else 'N'}, "
        f"Fib={'Y' if flags['fib'] else 'N'}, "
        f"Liq={'Y' if flags['liquidity'] else 'N'}, "
        f"Struct={'Y' if flags['structure'] else 'N'}, "
        f"4H={'Y' if flags['confirmation'] else 'N'}, "
        f"RR={'Y' if flags['rr'] else 'N'}"
    )

    result = ScanResult(
        symbol=symbol,
        direction=direction,
        confluence_score=confluence_score,
        htf_bias=notes["htf_bias"],
        location_note=notes["location"],
        fib_note=notes["fib"],
        liquidity_note=notes["liquidity"],
        structure_note=notes["structure"],
        confirmation_note=notes["confirmation"],
        rr_note=notes["rr"],
        summary_reason=summary,
        status=status,
        entry=entry,
        stop_loss=sl,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        tp4=tp4,
        tp5=tp5,
        setup_type=setup_type,
        what_to_look_for=what_to_look_for,
    )

    return result


def scan_group(symbols: List[str]) -> Tuple[List[ScanResult], List[ScanResult]]:
    results: List[ScanResult] = []
    trade_ideas: List[ScanResult] = []

    for sym in symbols:
        res = scan_single_asset(sym)
        if not res:
            continue
        results.append(res)
        if res.status in ("active", "in_progress"):
            trade_ideas.append(res)

    return results, trade_ideas


def scan_forex() -> Tuple[List[ScanResult], List[ScanResult]]:
    return scan_group(FOREX_PAIRS)


def scan_crypto() -> Tuple[List[ScanResult], List[ScanResult]]:
    return scan_group(CRYPTO_ASSETS)


def scan_metals() -> Tuple[List[ScanResult], List[ScanResult]]:
    return scan_group(METALS)


def scan_indices() -> Tuple[List[ScanResult], List[ScanResult]]:
    return scan_group(INDICES)


def scan_energies() -> Tuple[List[ScanResult], List[ScanResult]]:
    return scan_group(ENERGIES)


def scan_all_markets() -> Dict[str, Tuple[List[ScanResult], List[ScanResult]]]:
    markets: Dict[str, Tuple[List[ScanResult], List[ScanResult]]] = {}

    fx_results, fx_trades = scan_forex()
    markets["Forex"] = (fx_results, fx_trades)

    metals_results, metals_trades = scan_metals()
    markets["Metals"] = (metals_results, metals_trades)

    indices_results, indices_trades = scan_indices()
    markets["Indices"] = (indices_results, indices_trades)

    energies_results, energies_trades = scan_energies()
    markets["Energies"] = (energies_results, energies_trades)

    crypto_results, crypto_trades = scan_crypto()
    markets["Crypto"] = (crypto_results, crypto_trades)

    return markets
