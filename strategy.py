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


# ========= Data structure =========


@dataclass
class ScanResult:
    symbol: str
    direction: str  # "bullish" or "bearish"
    confluence_score: int
    htf_bias: str
    location_note: str
    fib_note: str
    liquidity_note: str
    structure_note: str
    confirmation_note: str
    rr_note: str
    summary_reason: str
    status: str = "scan_only"  # "scan_only", "in_progress", "active"
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    tp4: Optional[float] = None
    tp5: Optional[float] = None


# ========= Generic helpers =========


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
    """
    Find simple swing highs/lows using a symmetric lookback window.

    Returns:
        highs: list of (index, price)
        lows:  list of (index, price)
    """
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


def _infer_trend(candles: List[Dict]) -> str:
    """
    Simple HH/HL vs LH/LL based trend inference using pivots.
    Returns "bullish", "bearish", or "mixed".
    """
    highs, lows = _find_pivots(candles)
    if len(highs) < 2 or len(lows) < 2:
        # Fallback: compare last close to close N bars ago
        if len(candles) < 5:
            return "mixed"
        if candles[-1]["close"] > candles[-5]["close"]:
            return "bullish"
        if candles[-1]["close"] < candles[-5]["close"]:
            return "bearish"
        return "mixed"

    # Use last two meaningful highs and lows
    last_highs = highs[-2:]
    last_lows = lows[-2:]

    _, h1 = last_highs[0]
    _, h2 = last_highs[1]
    _, l1 = last_lows[0]
    _, l2 = last_lows[1]

    if h2 > h1 and l2 > l1:
        return "bullish"
    if h2 < h1 and l2 < l1:
        return "bearish"
    return "mixed"


def _infer_daily_trend(daily_candles: List[Dict]) -> str:
    """
    Exposed for backtest module.
    """
    return _infer_trend(daily_candles)


def _range_position(
    candles: List[Dict],
    price: float,
) -> Tuple[Tuple[float, float], str, bool]:
    """
    Compute [low, high] of a window and whether price is in lower/upper edge or mid.
    Returns: (range_low, range_high), note, edge_flag
    """
    r_low, r_high = _safe_min_max(candles)
    if r_low != r_low or r_high != r_high:  # NaN check
        return (r_low, r_high), "range: N/A", False

    span = r_high - r_low
    if span <= 0:
        return (r_low, r_high), f"range: {r_low:.5f}–{r_high:.5f}", False

    lower_band = r_low + span * 0.33
    upper_band = r_low + span * 0.67

    if price <= lower_band:
        note = f"price in lower edge of range ({r_low:.5f}–{r_high:.5f})"
        return (r_low, r_high), note, True
    elif price >= upper_band:
        note = f"price in upper edge of range ({r_low:.5f}–{r_high:.5f})"
        return (r_low, r_high), note, True
    else:
        note = f"price mid-range ({r_low:.5f}–{r_high:.5f}), no clear edge"
        return (r_low, r_high), note, False


# ========= S/R & Supply/Demand helpers =========


def _cluster_prices(prices: List[float], tolerance_pct: float = 0.25) -> List[Tuple[float, int]]:
    """
    Cluster nearby prices (within tolerance_pct %) into levels and count taps.
    Returns list of (level_price, taps).
    """
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


def _build_sr_levels(candles: List[Dict], tolerance_pct: float = 0.25) -> List[Dict]:
    """
    Build basic S/R levels from pivots and cluster them.
    Each level: {"price": float, "taps": int, "tier": int}
    Tier 1: >=4 taps, Tier 2: >=2 taps, Tier 3: 1 tap.
    """
    highs, lows = _find_pivots(candles)
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
    """
    Pick nearest S/R level to price and annotate with distance in %.
    """
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
    zone_type: str,  # "supply" or "demand"
    lookback: int = 80,
) -> Optional[Tuple[float, float, float]]:
    """
    Approximate nearest supply/demand zone using candle ranges:
    - For supply: use candles whose mid is above price.
    - For demand: use candles whose mid is below price.
    Returns (zone_low, zone_high, distance_pct) or None.
    """
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


# ========= Bias / Fib / Liquidity / Structure / 4H / R:R =========


def _pick_direction_from_bias(
    monthly_trend: str,
    weekly_trend: str,
    daily_trend: str,
) -> Tuple[str, str, bool]:
    """
    Decide trade direction + descriptive HTF bias note + boolean flag whether bias is 'strong enough'
    according to the Blueprint spec (weekly + daily agree, monthly as context).
    """
    note_parts: List[str] = []
    strong = False
    direction = "neutral"

    # Primary: Weekly leads, Daily can be mixed (pullbacks are acceptable)
    if weekly_trend in ("bullish", "bearish"):
        direction = weekly_trend
        
        if weekly_trend == daily_trend:
            # Perfect alignment
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
            # Weekly leads with Daily pullback/consolidation - acceptable
            strong = True
            note_parts.append(
                f"HTF bias: Weekly={weekly_trend} leading, Daily={daily_trend} (pullback/consolidation phase acceptable)."
            )
        else:
            # Counter-trend: Weekly and Daily oppose
            strong = False
            note_parts.append(
                f"HTF bias mixed: Weekly={weekly_trend} vs Daily={daily_trend} (counter-trend conflict)."
            )
    else:
        # Weekly is mixed, fall back to Daily
        if daily_trend in ("bullish", "bearish"):
            direction = daily_trend
        else:
            direction = "bullish"  # arbitrary fallback

        note_parts.append(
            f"HTF bias weak: Monthly={monthly_trend}, Weekly={weekly_trend}, Daily={daily_trend} (no clear HTF trend)."
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
    """
    Location check for Blueprint strategy:
    - Price should be near HTF S/R levels or supply/demand zones
    - For longs: prefer lower/support areas
    - For shorts: prefer upper/resistance areas
    - More flexible than strict polarity to catch valid retracement entries
    """
    notes: List[str] = []
    location_score = 0  # Track how many location criteria are met

    zone_type = "supply" if direction == "bearish" else "demand"

    # === Monthly ===
    (mn_low, mn_high), mn_note, mn_edge = _range_position(monthly_candles, price)
    notes.append(f"Monthly: {mn_note}.")
    if mn_edge:
        location_score += 2  # HTF edge is very important

    mn_levels = _build_sr_levels(monthly_candles) if monthly_candles else []
    mn_near = _nearest_sr_level(mn_levels, price)
    if mn_near:
        notes.append(
            f"Monthly: nearest Tier {mn_near['tier']} S/R around {mn_near['price']:.5f} "
            f"(≈{mn_near['taps']} taps, dist≈{mn_near['dist_pct']:.2f}%)."
        )
        if mn_near["dist_pct"] <= 1.0:  # Within 1% of monthly S/R
            location_score += 2
        elif mn_near["dist_pct"] <= 2.0:  # Within 2% of monthly S/R
            location_score += 1

    mn_zone = _approx_near_zone(monthly_candles, price, zone_type, lookback=120)
    if mn_zone:
        z_low, z_high, z_dist = mn_zone
        side = "below" if zone_type == "supply" else "above"
        notes.append(
            f"Monthly: current price {side} {zone_type} zone around [{z_low:.5f}–{z_high:.5f}] "
            f"(dist≈{z_dist:.2f}%)."
        )
        if z_dist <= 1.5:
            location_score += 1

    # === Weekly ===
    (wk_low, wk_high), wk_note, wk_edge = _range_position(weekly_candles, price)
    notes.append(f"Weekly: {wk_note}.")
    if wk_edge:
        location_score += 2

    wk_levels = _build_sr_levels(weekly_candles) if weekly_candles else []
    wk_near = _nearest_sr_level(wk_levels, price)
    if wk_near:
        notes.append(
            f"Weekly: nearest Tier {wk_near['tier']} S/R around {wk_near['price']:.5f} "
            f"(≈{wk_near['taps']} taps, dist≈{wk_near['dist_pct']:.2f}%)."
        )
        if wk_near["dist_pct"] <= 0.75:  # Within 0.75% of weekly S/R
            location_score += 2
        elif wk_near["dist_pct"] <= 1.5:
            location_score += 1

    wk_zone = _approx_near_zone(weekly_candles, price, zone_type, lookback=160)
    if wk_zone:
        z_low, z_high, z_dist = wk_zone
        side = "below" if zone_type == "supply" else "above"
        notes.append(
            f"Weekly: current price {side} {zone_type} zone around [{z_low:.5f}–{z_high:.5f}] "
            f"(dist≈{z_dist:.2f}%)."
        )
        if z_dist <= 1.5:
            location_score += 1

    # === Daily ===
    (d_low, d_high), d_note, d_edge = _range_position(daily_candles, price)
    notes.append(f"Daily: {d_note}.")

    # Track position relative to daily range for directional context
    if d_low == d_low and d_high == d_high:  # not NaN
        mid = (d_low + d_high) / 2.0
        range_pct = (price - d_low) / (d_high - d_low) if (d_high - d_low) > 0 else 0.5
        
        if direction == "bullish":
            # For longs, we want to be in lower portion (retracement)
            if range_pct <= 0.4:
                notes.append("Daily: price in lower portion of range, favorable for long entry.")
                location_score += 1
            elif range_pct <= 0.55:
                notes.append("Daily: price near middle of range.")
        else:
            # For shorts, we want to be in upper portion
            if range_pct >= 0.6:
                notes.append("Daily: price in upper portion of range, favorable for short entry.")
                location_score += 1
            elif range_pct >= 0.45:
                notes.append("Daily: price near middle of range.")

    if d_edge:
        location_score += 1

    d_levels = _build_sr_levels(daily_candles) if daily_candles else []
    d_near = _nearest_sr_level(d_levels, price)
    if d_near:
        notes.append(
            f"Daily: nearest Tier {d_near['tier']} S/R around {d_near['price']:.5f} "
            f"(≈{d_near['taps']} taps, dist≈{d_near['dist_pct']:.2f}%)."
        )
        if d_near["dist_pct"] <= 0.5:
            location_score += 1

    d_zone = _approx_near_zone(daily_candles, price, zone_type, lookback=120)
    if d_zone:
        z_low, z_high, z_dist = d_zone
        side = "below" if zone_type == "supply" else "above"
        notes.append(
            f"Daily: current price {side} {zone_type} zone around [{z_low:.5f}–{z_high:.5f}] "
            f"(dist≈{z_dist:.2f}%)."
        )
        if z_dist <= 1.0:
            location_score += 1

    # Location is OK if we have reasonable confluence of location factors
    # Threshold of 2 means at least one significant HTF factor
    ok = location_score >= 2
    
    if ok:
        notes.append(f"Location confluence score: {location_score} (sufficient).")
    else:
        notes.append(f"Location confluence score: {location_score} (insufficient, need ≥2).")
    
    return " ".join(notes), ok


def _find_last_swing_leg_for_fib(
    candles: List[Dict],
    direction: str,
) -> Optional[Tuple[float, float]]:
    """
    Use pivots to approximate the last impulsive leg for Fib retracement.
    Returns (leg_low, leg_high) in price terms, or None if not found.
    """
    highs, lows = _find_pivots(candles)
    if not highs or not lows:
        return None

    if direction == "bullish":
        # low -> high leg
        hi_idx, hi_price = highs[-1]
        candidate_lows = [pl for pl in lows if pl[0] < hi_idx]
        if not candidate_lows:
            return None
        lo_idx, lo_price = candidate_lows[-1]
        if lo_price >= hi_price:
            return None
        return lo_price, hi_price
    else:
        # bearish: high -> low leg (we still return low<high; formula handles direction)
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
    """
    Fibonacci logic on WEEKLY & DAILY as per Blueprint:
    - Use meaningful impulse legs (body->wick approximation via pivots).
    - Compute golden pockets (0.618-0.796) and extended zones (0.5-0.85).
    - Fib confluence = True if price is in or near retracement zones.
    """
    notes: List[str] = []
    fib_score = 0

    # --- Weekly leg ---
    weekly_leg = _find_last_swing_leg_for_fib(weekly_candles, direction) if weekly_candles else None
    if weekly_leg:
        w_low, w_high = weekly_leg
        span = w_high - w_low
        
        if direction == "bullish":
            # For bullish, retracement goes down from high
            w_gp_low = w_low + span * 0.618
            w_gp_high = w_low + span * 0.796
            # Extended zone (50% - 85% retracement)
            w_ext_low = w_low + span * 0.50
            w_ext_high = w_low + span * 0.85
        else:
            # For bearish, retracement goes up from low
            w_gp_low = w_high - span * 0.796
            w_gp_high = w_high - span * 0.618
            w_ext_low = w_high - span * 0.85
            w_ext_high = w_high - span * 0.50

        w_in_gp = w_gp_low <= price <= w_gp_high
        w_in_ext = w_ext_low <= price <= w_ext_high
        
        if w_in_gp:
            notes.append(
                f"Weekly: price inside golden pocket ({w_gp_low:.5f}–{w_gp_high:.5f}) of last impulse leg."
            )
            fib_score += 3  # Strong fib confluence
        elif w_in_ext:
            notes.append(
                f"Weekly: price in extended retracement zone ({w_ext_low:.5f}–{w_ext_high:.5f}) of last impulse leg."
            )
            fib_score += 2  # Moderate fib confluence
        else:
            notes.append(
                f"Weekly: price outside retracement zone ({w_ext_low:.5f}–{w_ext_high:.5f}) of last impulse leg "
                f"(current={price:.5f})."
            )
    else:
        notes.append("Weekly: no clear impulse leg for Fibonacci.")

    # --- Daily leg ---
    daily_leg = _find_last_swing_leg_for_fib(daily_candles, direction) if daily_candles else None
    if daily_leg:
        d_low, d_high = daily_leg
        span = d_high - d_low
        
        if direction == "bullish":
            d_gp_low = d_low + span * 0.618
            d_gp_high = d_low + span * 0.796
            d_ext_low = d_low + span * 0.50
            d_ext_high = d_low + span * 0.85
        else:
            d_gp_low = d_high - span * 0.796
            d_gp_high = d_high - span * 0.618
            d_ext_low = d_high - span * 0.85
            d_ext_high = d_high - span * 0.50

        d_in_gp = d_gp_low <= price <= d_gp_high
        d_in_ext = d_ext_low <= price <= d_ext_high
        
        if d_in_gp:
            notes.append(
                f"Daily: price inside golden pocket ({d_gp_low:.5f}–{d_gp_high:.5f}) of last impulse leg."
            )
            fib_score += 3
        elif d_in_ext:
            notes.append(
                f"Daily: price in extended retracement zone ({d_ext_low:.5f}–{d_ext_high:.5f}) of last impulse leg."
            )
            fib_score += 2
        else:
            notes.append(
                f"Daily: price outside retracement zone ({d_ext_low:.5f}–{d_ext_high:.5f}) of last impulse leg "
                f"(current={price:.5f})."
            )
    else:
        notes.append("Daily: no clear impulse leg for Fibonacci.")

    # If neither leg exists → no Fib confluence.
    if not weekly_leg and not daily_leg:
        return "Weekly/Daily: no clear impulse legs for Fibonacci (skipping Fib confluence).", False

    # Fib OK if we have at least some retracement confluence
    fib_ok = fib_score >= 2
    
    if fib_ok:
        notes.append(f"Fib confluence score: {fib_score} (sufficient).")
    else:
        notes.append(f"Fib confluence score: {fib_score} (insufficient, need ≥2).")

    return " ".join(notes), fib_ok


def _daily_liquidity_context(
    daily_candles: List[Dict],
    price: float,
) -> Tuple[str, bool]:
    """
    Liquidity & liquidity flows (Daily):
    - External liquidity: extremes of the sampled range.
    - Internal liquidity: equal highs / equal lows clusters.
    - Sweeps: last candle runs external high/low and closes back inside.
    """
    if not daily_candles:
        return "Daily: no liquidity data.", False

    notes: List[str] = []
    ok = False

    lows = [c["low"] for c in daily_candles]
    highs = [c["high"] for c in daily_candles]
    low_ext = min(lows)
    high_ext = max(highs)

    last = daily_candles[-1]

    # --- External liquidity sweeps (liquidity flows idea) ---
    # Check last 5 candles for sweeps instead of just the last one
    sweep_lookback = 5  # How many recent candles to check for sweeps
    history_window = 100  # How far back to look for the baseline extremes
    
    if len(daily_candles) > sweep_lookback:
        for i in range(1, sweep_lookback + 1):
            candle_idx = len(daily_candles) - i
            recent_candle = daily_candles[candle_idx]
            
            # Get baseline from candles BEFORE this one, bounded to history_window
            start_idx = max(0, candle_idx - history_window)
            prev_candles = daily_candles[start_idx:candle_idx]
            
            if len(prev_candles) < 10:  # Need sufficient history
                continue
                
            prev_lows = [c["low"] for c in prev_candles]
            prev_highs = [c["high"] for c in prev_candles]
            prev_low_ext = min(prev_lows)
            prev_high_ext = max(prev_highs)

            swept_down = recent_candle["low"] < prev_low_ext and recent_candle["close"] > prev_low_ext
            swept_up = recent_candle["high"] > prev_high_ext and recent_candle["close"] < prev_high_ext

            if swept_down:
                notes.append(
                    f"Daily: recent sweep of external liquidity below {prev_low_ext:.5f} with close back above ({i} candles ago)."
                )
                ok = True
                break
            elif swept_up:
                notes.append(
                    f"Daily: recent sweep of external liquidity above {prev_high_ext:.5f} with close back below ({i} candles ago)."
                )
                ok = True
                break

    # --- External liquidity magnets (next targets) ---
    dist_high = _percent_distance(price, high_ext)
    dist_low = _percent_distance(price, low_ext)

    if dist_high < dist_low:
        pool = high_ext
        side = "above"
    else:
        pool = low_ext
        side = "below"

    notes.append(
        f"Daily: main external liquidity pool {side} current price around {pool:.5f}."
    )

    near_external = min(dist_high, dist_low) <= 2.5

    if near_external:
        ok = True

    # --- Internal equal highs / equal lows (internal liquidity) ---
    highs_piv, lows_piv = _find_pivots(daily_candles)

    def _find_equal_level(
        pivots: List[Tuple[int, float]],
        tol_pct: float = 0.05,
    ) -> Optional[float]:
        if len(pivots) < 2:
            return None
        n = len(pivots)
        for i in range(max(0, n - 8), n):
            for j in range(i + 1, n):
                p1 = pivots[i][1]
                p2 = pivots[j][1]
                if _percent_distance(p1, p2) <= tol_pct:
                    return (p1 + p2) / 2.0
        return None

    eq_high = _find_equal_level(highs_piv)
    eq_low = _find_equal_level(lows_piv)

    if eq_high is not None:
        notes.append(
            f"Daily: internal equal highs cluster around {eq_high:.5f} (liquidity)."
        )
        if _percent_distance(price, eq_high) <= 2.5:
            ok = True

    if eq_low is not None:
        notes.append(
            f"Daily: internal equal lows cluster around {eq_low:.5f} (liquidity)."
        )
        if _percent_distance(price, eq_low) <= 2.5:
            ok = True

    note = " ".join(notes)
    return note, ok


# ========= Structural frameworks (Daily) =========


def _find_swings(
    candles: List[Dict],
    left: int = 2,
    right: int = 2,
) -> Tuple[List[int], List[int]]:
    """
    Find swing highs and swing lows indices in a candle list.
    swing high: high >= highs of 'left' candles before and 'right' candles after.
    swing low: low <= lows of 'left' candles before and 'right' candles after.
    """
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    n = len(candles)

    swing_highs: List[int] = []
    swing_lows: List[int] = []

    for i in range(left, n - right):
        h = highs[i]
        if all(h >= highs[j] for j in range(i - left, i + right + 1)):
            swing_highs.append(i)

        l = lows[i]
        if all(l <= lows[j] for j in range(i - left, i + right + 1)):
            swing_lows.append(i)

    return swing_highs, swing_lows


def _detect_structural_frameworks_d1(
    d_candles: List[Dict],
    direction: str,
) -> Tuple[bool, Optional[str], str]:
    """
    Detect Daily structural frameworks:
    - Bearish Head & Shoulders
    - Bullish Inverse Head & Shoulders
    - Bullish N (continuation)
    - Bearish V (continuation)

    Returns:
        (framework_ok, framework_name, framework_note)
    """
    if not d_candles or len(d_candles) < 50:
        return False, None, "Daily framework: not enough data to evaluate."

    swing_highs, swing_lows = _find_swings(d_candles, left=2, right=2)
    closes = [c["close"] for c in d_candles]
    highs = [c["high"] for c in d_candles]
    lows = [c["low"] for c in d_candles]

    framework_ok = False
    framework_name: Optional[str] = None
    note_parts: List[str] = []

    # --- 1) Try to detect H&S / inverse H&S on the last ~80 candles ---
    lookback = 80
    start = max(0, len(d_candles) - lookback)
    sh = [i for i in swing_highs if i >= start]
    sl = [i for i in swing_lows if i >= start]

    # Bearish Head & Shoulders (reversal short)
    if len(sh) >= 3:
        # take last 3 swing highs as candidate shoulder-head-shoulder
        h1, h2, h3 = sh[-3], sh[-2], sh[-1]
        if highs[h2] > highs[h1] and highs[h2] > highs[h3]:
            # neck lows: min lows between h1-h2 and h2-h3
            neck1 = min(lows[h1 : h2 + 1])
            neck2 = min(lows[h2 : h3 + 1])
            neckline = (neck1 + neck2) / 2.0
            last_close = closes[-1]

            if last_close < neckline * 0.999:  # broke neckline
                framework_ok = direction == "bearish"
                framework_name = "Bearish Head & Shoulders"
                note_parts.append(
                    f"Daily H&S detected: head at index {h2}, neckline ≈ {neckline:.5f}, "
                    f"price closed below neckline."
                )

    # Bullish Inverse H&S (reversal long)
    if not framework_ok and len(sl) >= 3:
        l1, l2, l3 = sl[-3], sl[-2], sl[-1]
        if lows[l2] < lows[l1] and lows[l2] < lows[l3]:
            # neck highs: max highs between l1-l2 and l2-l3
            neck1 = max(highs[l1 : l2 + 1])
            neck2 = max(highs[l2 : l3 + 1])
            neckline = (neck1 + neck2) / 2.0
            last_close = closes[-1]

            if last_close > neckline * 1.001:  # broke neckline
                framework_ok = direction == "bullish"
                framework_name = "Bullish Inverse Head & Shoulders"
                note_parts.append(
                    f"Daily inverse H&S detected: head at index {l2}, neckline ≈ {neckline:.5f}, "
                    f"price closed above neckline."
                )

    # --- 2) Try to detect Bullish N / Bearish V continuation patterns ---
    if not framework_ok:
        # Bullish N (continuation)
        if direction == "bullish" and len(sl) >= 2 and len(sh) >= 1:
            last_low_idx = sl[-1]
            prev_low_idx = sl[-2]
            max_high_idx = max(sh)  # coarse approx for leg-1 high

            if prev_low_idx < max_high_idx < last_low_idx:
                l1_low = lows[prev_low_idx]
                l2_low = lows[last_low_idx]
                h1 = highs[max_high_idx]
                if h1 > l1_low and l2_low > l1_low:
                    framework_ok = True
                    framework_name = "Bullish N (continuation)"
                    note_parts.append(
                        "Daily Bullish N pattern: impulse up, corrective pullback forming a higher low."
                    )

        # Bearish V (continuation)
        if direction == "bearish" and len(sh) >= 2 and len(sl) >= 1:
            last_high_idx = sh[-1]
            prev_high_idx = sh[-2]
            min_low_idx = min(sl)  # coarse approx for leg-1 low

            if prev_high_idx < min_low_idx < last_high_idx:
                h1_high = highs[prev_high_idx]
                l1_low = lows[min_low_idx]
                h2_high = highs[last_high_idx]
                if l1_low < h1_high and h2_high < h1_high:
                    framework_ok = True
                    framework_name = "Bearish V (continuation)"
                    note_parts.append(
                        "Daily Bearish V pattern: impulse down, corrective bounce forming a lower high."
                    )

    if framework_ok and framework_name:
        note_parts.insert(0, f"Daily framework: {framework_name}.")
    else:
        if not note_parts:
            note_parts.append("Daily framework: none clearly detected.")

    return framework_ok, framework_name, " ".join(note_parts)


def _structure_context(
    monthly_candles: List[Dict],
    weekly_candles: List[Dict],
    daily_candles: List[Dict],
    direction: str,
) -> Tuple[bool, str]:
    """
    Evaluate Weekly + Daily structure AND Daily frameworks (H&S, inverse H&S, N/V).

    Returns:
        (structure_ok, struct_note)
    """

    def _trend_from_swings(candles: List[Dict]) -> str:
        if not candles or len(candles) < 20:
            return "mixed"

        swing_highs_idx, swing_lows_idx = _find_swings(candles, left=2, right=2)

        if len(swing_highs_idx) < 2 or len(swing_lows_idx) < 2:
            return "mixed"

        highs = [candles[i]["high"] for i in swing_highs_idx]
        lows = [candles[i]["low"] for i in swing_lows_idx]

        # very coarse: last two highs/lows
        h1, h2 = highs[-2], highs[-1]
        l1, l2 = lows[-2], lows[-1]

        if h2 > h1 and l2 > l1:
            return "bullish"
        if h2 < h1 and l2 < l1:
            return "bearish"
        return "mixed"

    w_trend = _trend_from_swings(weekly_candles)
    d_trend = _trend_from_swings(daily_candles)

    parts: List[str] = []
    parts.append(f"Weekly structure: {w_trend}.")
    parts.append(f"Daily structure: {d_trend}.")

    # --- framework detection on Daily ---
    framework_ok, framework_name, framework_note = _detect_structural_frameworks_d1(
        daily_candles, direction
    )
    parts.append(framework_note)

    structure_ok = False

    # 1) pure trend alignment
    if direction == "bullish":
        if w_trend == "bullish" and d_trend in ("bullish", "mixed"):
            structure_ok = True
    elif direction == "bearish":
        if w_trend == "bearish" and d_trend in ("bearish", "mixed"):
            structure_ok = True

    # 2) OR we accept a strong reversal framework
    if framework_ok:
        structure_ok = True

    if structure_ok:
        if framework_ok and framework_name:
            parts.append(
                f"Structure supports {direction} idea via Daily {framework_name} and HTF trend context."
            )
        else:
            parts.append(
                f"Structure supports {direction} idea via Weekly/Daily trend alignment."
            )
    else:
        parts.append(
            f"Structure does NOT cleanly support {direction} idea (trend/framework mismatch)."
        )

    return structure_ok, " ".join(parts)


def _daily_confirmation_fallback(
    daily_candles: List[Dict],
    direction: str,
) -> Tuple[str, bool]:
    """
    Fallback confirmation using Daily candles when H4 data is not available.
    Uses similar logic to H4 confirmation but on Daily timeframe.
    """
    if not daily_candles or len(daily_candles) < 20:
        return "Daily fallback: not enough data for confirmation.", False

    swing_highs, swing_lows = _find_swings(daily_candles, left=2, right=2)
    
    notes: List[str] = []
    confirmation_score = 0
    
    if direction == "bearish":
        # Check for BOS down (break below swing low)
        if swing_lows and len(swing_lows) >= 1:
            relevant_swing_lows = [idx for idx in swing_lows if idx < len(daily_candles) - 2]
            if relevant_swing_lows:
                key_idx = relevant_swing_lows[-1]
                key_level = daily_candles[key_idx]["low"]
                
                for i in range(1, min(4, len(daily_candles))):
                    if daily_candles[-i]["close"] < key_level:
                        notes.append(f"Daily: BOS down confirmed – close below swing low {key_level:.5f}.")
                        confirmation_score += 3
                        break
        
        # Check for bearish momentum candle
        for i in range(1, min(3, len(daily_candles))):
            candle = daily_candles[-i]
            body = candle["open"] - candle["close"]
            total_range = candle["high"] - candle["low"]
            if total_range > 0 and body > 0:
                body_ratio = body / total_range
                if body_ratio >= 0.55:
                    notes.append(f"Daily: bearish momentum candle detected (body ratio {body_ratio:.1%}).")
                    confirmation_score += 2
                    break
        
        # Check for bearish engulfing
        if len(daily_candles) >= 2:
            curr = daily_candles[-1]
            prev = daily_candles[-2]
            if curr["close"] < curr["open"] and prev["close"] > prev["open"]:
                if curr["open"] >= prev["close"] and curr["close"] <= prev["open"]:
                    notes.append("Daily: bearish engulfing pattern detected.")
                    confirmation_score += 2
        
    else:  # bullish
        # Check for BOS up (break above swing high)
        if swing_highs and len(swing_highs) >= 1:
            relevant_swing_highs = [idx for idx in swing_highs if idx < len(daily_candles) - 2]
            if relevant_swing_highs:
                key_idx = relevant_swing_highs[-1]
                key_level = daily_candles[key_idx]["high"]
                
                for i in range(1, min(4, len(daily_candles))):
                    if daily_candles[-i]["close"] > key_level:
                        notes.append(f"Daily: BOS up confirmed – close above swing high {key_level:.5f}.")
                        confirmation_score += 3
                        break
        
        # Check for bullish momentum candle
        for i in range(1, min(3, len(daily_candles))):
            candle = daily_candles[-i]
            body = candle["close"] - candle["open"]
            total_range = candle["high"] - candle["low"]
            if total_range > 0 and body > 0:
                body_ratio = body / total_range
                if body_ratio >= 0.55:
                    notes.append(f"Daily: bullish momentum candle detected (body ratio {body_ratio:.1%}).")
                    confirmation_score += 2
                    break
        
        # Check for bullish engulfing
        if len(daily_candles) >= 2:
            curr = daily_candles[-1]
            prev = daily_candles[-2]
            if curr["close"] > curr["open"] and prev["close"] < prev["open"]:
                if curr["open"] <= prev["close"] and curr["close"] >= prev["open"]:
                    notes.append("Daily: bullish engulfing pattern detected.")
                    confirmation_score += 2
    
    confirmed = confirmation_score >= 2
    
    if confirmed:
        notes.append(f"Daily confirmation score: {confirmation_score} (sufficient, using Daily fallback).")
    else:
        notes.append(f"Daily confirmation score: {confirmation_score} (insufficient, need ≥2).")
    
    return " ".join(notes) if notes else "Daily fallback: no clear confirmation signals.", confirmed


def _h4_confirmation(
    h4_candles: List[Dict],
    direction: str,
    daily_candles: List[Dict] = None,
) -> Tuple[str, bool]:
    """
    4H confirmation approximation in Blueprint terms:
    - We want a BOS (break of structure) in the trade direction.
    - For shorts: recent close below a meaningful swing low.
    - For longs: recent close above a meaningful swing high.
    - Also checks for momentum candles and engulfing patterns.
    - Falls back to Daily data if H4 is not available.
    """
    # Fallback to Daily data if H4 is not available
    if not h4_candles or len(h4_candles) < 20:
        if daily_candles and len(daily_candles) >= 20:
            return _daily_confirmation_fallback(daily_candles, direction)
        return "4H: not enough data for confirmation.", False

    swing_highs, swing_lows = _find_swings(h4_candles, left=2, right=2)
    
    # Check recent candles for confirmation (last 5-10 candles)
    lookback = min(10, len(h4_candles) - 1)
    recent_candles = h4_candles[-lookback:]
    
    notes: List[str] = []
    confirmation_score = 0
    
    if direction == "bearish":
        # Check for BOS down (break below swing low)
        if swing_lows and len(swing_lows) >= 1:
            # Get swing lows from the lookback period
            relevant_swing_lows = [idx for idx in swing_lows if idx < len(h4_candles) - 3]
            if relevant_swing_lows:
                key_idx = relevant_swing_lows[-1]
                key_level = h4_candles[key_idx]["low"]
                
                # Check if any recent close is below this swing low
                for i in range(1, min(6, len(h4_candles))):
                    if h4_candles[-i]["close"] < key_level:
                        notes.append(f"4H: BOS down confirmed – close below swing low {key_level:.5f}.")
                        confirmation_score += 3
                        break
        
        # Check for bearish momentum candle
        for i in range(1, min(4, len(h4_candles))):
            candle = h4_candles[-i]
            body = candle["open"] - candle["close"]
            total_range = candle["high"] - candle["low"]
            if total_range > 0 and body > 0:  # Bearish candle
                body_ratio = body / total_range
                if body_ratio >= 0.6:  # Strong bearish body
                    notes.append(f"4H: strong bearish candle detected (body ratio {body_ratio:.1%}).")
                    confirmation_score += 2
                    break
        
        # Check for bearish engulfing
        if len(h4_candles) >= 2:
            curr = h4_candles[-1]
            prev = h4_candles[-2]
            if curr["close"] < curr["open"] and prev["close"] > prev["open"]:  # curr bearish, prev bullish
                if curr["open"] >= prev["close"] and curr["close"] <= prev["open"]:
                    notes.append("4H: bearish engulfing pattern detected.")
                    confirmation_score += 2
        
    else:  # bullish
        # Check for BOS up (break above swing high)
        if swing_highs and len(swing_highs) >= 1:
            relevant_swing_highs = [idx for idx in swing_highs if idx < len(h4_candles) - 3]
            if relevant_swing_highs:
                key_idx = relevant_swing_highs[-1]
                key_level = h4_candles[key_idx]["high"]
                
                # Check if any recent close is above this swing high
                for i in range(1, min(6, len(h4_candles))):
                    if h4_candles[-i]["close"] > key_level:
                        notes.append(f"4H: BOS up confirmed – close above swing high {key_level:.5f}.")
                        confirmation_score += 3
                        break
        
        # Check for bullish momentum candle
        for i in range(1, min(4, len(h4_candles))):
            candle = h4_candles[-i]
            body = candle["close"] - candle["open"]
            total_range = candle["high"] - candle["low"]
            if total_range > 0 and body > 0:  # Bullish candle
                body_ratio = body / total_range
                if body_ratio >= 0.6:  # Strong bullish body
                    notes.append(f"4H: strong bullish candle detected (body ratio {body_ratio:.1%}).")
                    confirmation_score += 2
                    break
        
        # Check for bullish engulfing
        if len(h4_candles) >= 2:
            curr = h4_candles[-1]
            prev = h4_candles[-2]
            if curr["close"] > curr["open"] and prev["close"] < prev["open"]:  # curr bullish, prev bearish
                if curr["open"] <= prev["close"] and curr["close"] >= prev["open"]:
                    notes.append("4H: bullish engulfing pattern detected.")
                    confirmation_score += 2
    
    # Confirmation is OK if we have enough signals
    confirmed = confirmation_score >= 2
    
    if confirmed:
        notes.append(f"4H confirmation score: {confirmation_score} (sufficient).")
    else:
        notes.append(f"4H confirmation score: {confirmation_score} (insufficient, need ≥2).")
    
    return " ".join(notes) if notes else "4H: no clear confirmation signals.", confirmed


def _atr(candles: List[Dict], period: int = 14) -> float:
    """Very simple ATR approximation using high-low only."""
    if len(candles) < 2:
        return 0.0
    inps = candles[-period:]
    trs = [c["high"] - c["low"] for c in inps]
    if not trs:
        return 0.0
    return sum(trs) / len(trs)


def _rr_context(
    daily_candles: List[Dict],
    direction: str,
) -> Tuple[
    str,
    bool,
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[float],
]:
    """
    R/R + trade levels (TP1–TP5) based on the *Daily impulse leg*.

    Logic:
    - Try to find the last meaningful Daily impulse leg via `_find_last_swing_leg_for_fib`.
    - Entry is approximated in the golden pocket (0.618–0.796) of that leg.
    - SL is placed beyond the swing extreme with a buffer.
    - TP1–TP5 are projected using Fib-style extensions of that leg:

        TP1: -0.25
        TP2: -0.65
        TP3: -1.00
        TP4: -1.42
        TP5: -2.00

      (For longs these are above the high, for shorts below the low.)

    - We mark the R/R pillar `True` as long as the first partial (TP1)
      is at least ~0.5R. This is more lenient than the original 1.5R
      so that valid Blueprint setups are not filtered out just because
      TP1 is relatively conservative.

    - If no clear impulse leg exists, we fall back to an ATR-based
      pseudo-R/R using 1×ATR stops and multi-R targets.
    """
    if not daily_candles:
        return "R/R: no data.", False, None, None, None, None, None, None, None

    current = daily_candles[-1]["close"]

    # ---- Try fib-based targets from the Daily impulse leg ----
    leg = _find_last_swing_leg_for_fib(daily_candles, direction)

    if leg:
        lo, hi = leg
        span = hi - lo
        if span > 0:
            # Golden pocket zone for entry
            if direction == "bullish":
                gp_low = lo + span * 0.618
                gp_high = lo + span * 0.796
                if gp_low <= current <= gp_high:
                    entry = current
                else:
                    entry = (gp_low + gp_high) / 2.0

                # SL below swing low with buffer
                sl = lo - span * 0.25
                risk = entry - sl

                # Extensions above high
                ext_factors = [0.25, 0.65, 1.0, 1.42, 2.0]
                tp1 = hi + span * ext_factors[0]
                tp2 = hi + span * ext_factors[1]
                tp3 = hi + span * ext_factors[2]
                tp4 = hi + span * ext_factors[3]
                tp5 = hi + span * ext_factors[4]

                if risk > 0:
                    rr1 = (tp1 - entry) / risk
                    rr_ok = rr1 >= 0.5
                    note = (
                        "R/R: using Daily impulse leg; entry in golden pocket, SL below swing low. "
                        "TP1–TP5 based on Fib extensions (-0.25, -0.65, -1.00, -1.42, -2.00). "
                        f"Approx first target ≈ {rr1:.1f}R."
                    )
                    return note, rr_ok, entry, sl, tp1, tp2, tp3, tp4, tp5

            else:  # bearish
                gp_low = hi - span * 0.796
                gp_high = hi - span * 0.618
                if gp_low <= current <= gp_high:
                    entry = current
                else:
                    entry = (gp_low + gp_high) / 2.0

                # SL above swing high with buffer
                sl = hi + span * 0.25
                risk = sl - entry

                # Extensions below low
                ext_factors = [0.25, 0.65, 1.0, 1.42, 2.0]
                tp1 = lo - span * ext_factors[0]
                tp2 = lo - span * ext_factors[1]
                tp3 = lo - span * ext_factors[2]
                tp4 = lo - span * ext_factors[3]
                tp5 = lo - span * ext_factors[4]

                if risk > 0:
                    rr1 = (entry - tp1) / risk
                    rr_ok = rr1 >= 0.5
                    note = (
                        "R/R: using Daily impulse leg; entry in golden pocket, SL above swing high. "
                        "TP1–TP5 based on Fib extensions (-0.25, -0.65, -1.00, -1.42, -2.00). "
                        f"Approx first target ≈ {rr1:.1f}R."
                    )
                    return note, rr_ok, entry, sl, tp1, tp2, tp3, tp4, tp5

    # ---- Fallback: ATR-based targets if no clean impulse leg ----
    atr = _atr(daily_candles)
    if atr <= 0:
        return (
            "R/R: no clear Daily impulse leg and ATR too small; skipping R/R.",
            False,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )

    entry = current
    if direction == "bullish":
        sl = entry - atr
        risk = atr
        if sl <= 0 or risk <= 0:
            return (
                "R/R: invalid SL level.",
                False,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
        tp1 = entry + risk * 1.5
        tp2 = entry + risk * 2.5
        tp3 = entry + risk * 4.0
        tp4 = entry + risk * 6.0
        tp5 = entry + risk * 8.0
        rr1 = (tp1 - entry) / risk
    else:
        sl = entry + atr
        risk = atr
        tp1 = entry - risk * 1.5
        tp2 = entry - risk * 2.5
        tp3 = entry - risk * 4.0
        tp4 = entry - risk * 6.0
        tp5 = entry - risk * 8.0
        rr1 = (entry - tp1) / risk

    rr_ok = rr1 >= 0.5
    note = (
        "R/R: no clear Daily impulse leg for Fib; using ATR-based pseudo-targets instead. "
        f"Approx first target ≈ {rr1:.1f}R."
    )
    return note, rr_ok, entry, sl, tp1, tp2, tp3, tp4, tp5


def _compute_confluence_flags(
    monthly_candles: List[Dict],
    weekly_candles: List[Dict],
    daily_candles: List[Dict],
    h4_candles: List[Dict],
    direction: str,
) -> Tuple[
    Dict[str, bool],
    Dict[str, str],
    Tuple[
        Optional[float],
        Optional[float],
        Optional[float],
        Optional[float],
        Optional[float],
        Optional[float],
        Optional[float],
    ],
]:
    """
    Core confluence evaluation:
    Returns:
    - flags: dict with booleans for each of the 7 pillars
    - notes: dict with rich explanation strings
    - trade_levels: (entry, sl, tp1, tp2, tp3, tp4, tp5)
    """
    price = daily_candles[-1]["close"] if daily_candles else float("nan")

    # 1) HTF bias
    mn_trend = _infer_trend(monthly_candles) if monthly_candles else "mixed"
    wk_trend = _infer_trend(weekly_candles) if weekly_candles else "mixed"
    d_trend = _infer_trend(daily_candles) if daily_candles else "mixed"
    _, htf_note_text, htf_ok = _pick_direction_from_bias(mn_trend, wk_trend, d_trend)

    # 2) Location (top-down ranges + S/R + supply/demand with polarity)
    loc_note, loc_ok = _location_context(
        monthly_candles, weekly_candles, daily_candles, price, direction
    )

    # 3) Fibonacci (Weekly & Daily legs)
    fib_note, fib_ok = _fib_context(weekly_candles, daily_candles, direction, price)

    # 4) Liquidity (Daily extremes + sweeps + equal H/L)
    liq_note, liq_ok = _daily_liquidity_context(daily_candles, price)

    # 5) Structure (Weekly + Daily + frameworks)
    struct_ok, struct_note = _structure_context(
        monthly_candles, weekly_candles, daily_candles, direction
    )

    # 6) 4H confirmation (with Daily fallback if H4 not available)
    conf_note, conf_ok = _h4_confirmation(h4_candles, direction, daily_candles)

    # 7) R/R & trade levels
    (
        rr_note,
        rr_ok,
        entry,
        sl,
        tp1,
        tp2,
        tp3,
        tp4,
        tp5,
    ) = _rr_context(daily_candles, direction)

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


# ========= Public scan functions =========


def scan_single_asset(symbol: str) -> Optional[ScanResult]:
    """
    Full top-down Blueprint scan for a single asset.
    Returns a ScanResult or None if data unavailable.
    """
    # Use as much history as OANDA reasonably allows, without exceeding 'count' limits.
    monthly = get_ohlcv(symbol, timeframe="M", count=240)   # ~20 years
    weekly = get_ohlcv(symbol, timeframe="W", count=520)    # ~10 years
    daily = get_ohlcv(symbol, timeframe="D", count=2000)    # ~8 years
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

    # Confluence thresholds based on strategy mode
    # Standard mode: need 4+ confluence factors
    # Aggressive mode: need 3+ confluence factors
    min_trade_conf = 4 if SIGNAL_MODE == "standard" else 3

    # Active: Need confirmation + R/R + enough confluence
    # In-progress: Good setup waiting for 4H confirmation
    if flags["confirmation"] and confluence_score >= min_trade_conf and flags["rr"]:
        status = "active"
    elif confluence_score >= min_trade_conf - 1 and flags["location"] and (flags["fib"] or flags["liquidity"]):
        status = "in_progress"
    else:
        status = "scan_only"

    summary = (
        f"{direction.upper()} candidate with {confluence_score}/7 confluence: "
        f"htf_bias={'yes' if flags['htf_bias'] else 'no'}, "
        f"location={'yes' if flags['location'] else 'no'}, "
        f"fib={'yes' if flags['fib'] else 'no'}, "
        f"liquidity={'yes' if flags['liquidity'] else 'no'}, "
        f"struct={'yes' if flags['structure'] else 'no'}, "
        f"4H_confirm={'yes' if flags['confirmation'] else 'no'}, "
        f"rr={'yes' if flags['rr'] else 'no'}."
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
    )

    print(
        f"[scan_single_asset] {symbol}: confluence {confluence_score}/7 (mode={SIGNAL_MODE}) -> {flags} | status={status}"
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