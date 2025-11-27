import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime

import os

from config import (
    DISCORD_TOKEN,
    SCAN_CHANNEL_ID,
    TRADES_CHANNEL_ID,
    TRADE_UPDATES_CHANNEL_ID,
    SCAN_INTERVAL_HOURS,
    FOREX_PAIRS,
    METALS,
    INDICES,
    ENERGIES,
    CRYPTO_ASSETS,
    SIGNAL_MODE,
    ACTIVE_ACCOUNT_PROFILE,
    get_profile_info,
)

from strategy import (
    scan_single_asset,
    scan_forex,
    scan_crypto,
    scan_metals,
    scan_indices,
    scan_energies,
    scan_all_markets,
    ScanResult,
)

from formatting import (
    format_scan_group,
    format_detailed_scan,
    format_autoscan_output,
    format_backtest_result,
)

from discord_output import (
    create_setup_embed,
    create_tp_hit_embed,
    create_sl_hit_embed,
    create_trade_closed_embed,
    build_confluence_list,
)

from position_sizing import calculate_position_size_5ers
from config import ACCOUNT_SIZE, RISK_PER_TRADE_PCT

from backtest import run_backtest
from data import get_ohlcv, get_cache_stats, clear_cache, get_current_prices
from risk_manager import get_risk_manager, RiskCheckResult, TradeRecord
from discord_output import create_phase_progress_embed
from trade_state import get_trade_state
from challenge_simulator import simulate_challenge_for_month, format_challenge_result


ACTIVE_TRADES: dict[str, ScanResult] = {}
TRADE_PROGRESS: dict[str, dict[str, bool]] = {}
TRADE_SIZING: dict[str, dict] = {}
TRADE_ENTRY_DATES: dict[str, object] = {}  # Track entry datetime for each trade


def split_message(text: str, limit: int = 1900) -> list[str]:
    """Split a long message into chunks under Discord's character limit."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""

    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            if current:
                chunks.append(current)
            current = line
        else:
            if current:
                current += "\n" + line
            else:
                current = line

    if current:
        chunks.append(current)

    return chunks


def _ensure_trade_progress(trade_key: str) -> None:
    """Make sure TRADE_PROGRESS has an entry for this trade key."""
    if trade_key not in TRADE_PROGRESS:
        TRADE_PROGRESS[trade_key] = {
            "tp1": False, "tp2": False, "tp3": False,
            "tp4": False, "tp5": False, "sl": False,
        }


def activate_trade(
    trade: ScanResult,
    entry_price: float,
    sizing: dict,
) -> tuple[bool, str]:
    """
    Activate a trade through the risk manager.
    
    Returns (success, message) tuple.
    """
    rm = get_risk_manager()
    trade_key = f"{trade.symbol}_{trade.direction}"
    
    if trade_key in ACTIVE_TRADES:
        return False, f"Trade {trade_key} already active"
    
    risk_usd = sizing.get("risk_usd", 100)
    lot_size = sizing.get("lot_size", 0.01)
    
    check_result, check_message = rm.can_add_trade(risk_usd=risk_usd)
    
    if check_result not in (RiskCheckResult.ALLOWED, RiskCheckResult.WARNING_NEAR_LIMIT):
        return False, check_message
    
    trade.entry = entry_price
    entry_time = datetime.utcnow()
    
    trade_record = TradeRecord(
        trade_id=trade_key,
        symbol=trade.symbol,
        direction=trade.direction,
        entry_price=entry_price,
        stop_loss=trade.stop_loss,
        lot_size=lot_size,
        risk_usd=risk_usd,
        risk_pct=RISK_PER_TRADE_PCT,
        entry_datetime=entry_time,
    )
    rm.open_trade(trade_record)
    
    ACTIVE_TRADES[trade_key] = trade
    TRADE_ENTRY_DATES[trade_key] = entry_time
    TRADE_SIZING[trade_key] = sizing
    _ensure_trade_progress(trade_key)
    
    warning = f" (Warning: {check_message})" if check_result == RiskCheckResult.WARNING_NEAR_LIMIT else ""
    return True, f"Trade activated. Open risk: ${rm.get_open_risk_usd():.2f}{warning}"


def close_trade_with_pnl(
    trade_key: str,
    exit_price: float,
    pnl_usd: float,
    reason: str = "Manual close",
) -> tuple[bool, str]:
    """
    Close a trade and update the risk manager.
    
    Returns (success, message) tuple.
    """
    rm = get_risk_manager()
    
    if trade_key not in ACTIVE_TRADES:
        return False, f"Trade {trade_key} not found"
    
    closed_trade = rm.close_trade(
        trade_id=trade_key,
        exit_price=exit_price,
        pnl_usd=pnl_usd,
    )
    
    ACTIVE_TRADES.pop(trade_key, None)
    TRADE_PROGRESS.pop(trade_key, None)
    TRADE_SIZING.pop(trade_key, None)
    TRADE_ENTRY_DATES.pop(trade_key, None)
    
    if closed_trade:
        return True, f"{reason}. P&L: ${pnl_usd:.2f}, Balance: ${rm.current_balance:.2f}"
    else:
        return True, f"{reason}. Trade not tracked in risk manager."


def clear_all_trades() -> tuple[int, str]:
    """
    Clear all active trades from tracking.
    
    Returns (count, message) tuple.
    """
    rm = get_risk_manager()
    count = len(ACTIVE_TRADES)
    
    for trade_key in list(ACTIVE_TRADES.keys()):
        rm.close_trade(
            trade_id=trade_key,
            exit_price=0,
            pnl_usd=0,
        )
    
    ACTIVE_TRADES.clear()
    TRADE_PROGRESS.clear()
    TRADE_SIZING.clear()
    TRADE_ENTRY_DATES.clear()
    
    return count, f"Cleared {count} trades. Open risk reset to ${rm.get_open_risk_usd():.2f}"


def _compute_trade_progress(idea: ScanResult, live_prices: dict = None) -> tuple[float, float]:
    """Compute (current_price, approx_RR) for a trade idea using live prices."""
    current_price = None
    
    if live_prices and idea.symbol in live_prices:
        price_data = live_prices[idea.symbol]
        current_price = price_data.get("mid", 0) if price_data else 0
    
    if not current_price or current_price <= 0:
        prices = get_current_prices([idea.symbol])
        if prices and idea.symbol in prices:
            current_price = prices[idea.symbol].get("mid", 0)
    
    if not current_price or current_price <= 0:
        return float("nan"), float("nan")

    if idea.entry is None or idea.stop_loss is None:
        return current_price, float("nan")

    entry = idea.entry
    sl = idea.stop_loss

    if idea.direction == "bullish":
        risk = entry - sl
        if risk <= 0:
            return current_price, float("nan")
        rr = (current_price - entry) / risk
    else:
        risk = sl - entry
        if risk <= 0:
            return current_price, float("nan")
        rr = (entry - current_price) / risk

    return current_price, rr


async def check_trade_updates(updates_channel: discord.abc.Messageable) -> None:
    """Check active trades for TP/SL hits and send updates using live prices."""
    if not ACTIVE_TRADES:
        return

    trade_state = get_trade_state()
    trade_keys = list(ACTIVE_TRADES.keys())
    
    all_symbols = list(set(ACTIVE_TRADES[k].symbol for k in trade_keys if k in ACTIVE_TRADES))
    live_prices = await asyncio.to_thread(get_current_prices, all_symbols) if all_symbols else {}

    for key in trade_keys:
        trade = ACTIVE_TRADES.get(key)
        if trade is None:
            continue

        live_price_data = live_prices.get(trade.symbol)
        if live_price_data:
            price = live_price_data.get("mid", 0)
            if price <= 0:
                print(f"[check_trade_updates] {trade.symbol}: Invalid live price, skipping update")
                continue
        else:
            print(f"[check_trade_updates] {trade.symbol}: Could not fetch live price, skipping update")
            continue
        _ensure_trade_progress(key)
        progress = TRADE_PROGRESS[key]

        entry = trade.entry
        sl = trade.stop_loss
        direction = trade.direction.lower()
        
        sizing = TRADE_SIZING.get(key, {})
        risk_usd = sizing.get("risk_usd", ACCOUNT_SIZE * RISK_PER_TRADE_PCT)
        lot_size = sizing.get("lot_size", 1.0)

        closed = False
        embeds_to_send = []

        trade_id = trade_state.generate_trade_id(trade.symbol, direction, entry)
        
        if sl is not None and not progress["sl"]:
            if (direction == "bullish" and price <= sl) or (direction == "bearish" and price >= sl):
                progress["sl"] = True
                closed = True
                
                if not trade_state.is_update_posted(trade_id, "sl"):
                    entry_dt = TRADE_ENTRY_DATES.get(key)
                    embed = create_sl_hit_embed(
                        symbol=trade.symbol,
                        direction=direction,
                        sl_price=sl,
                        result_usd=-risk_usd,
                        result_pct=-RISK_PER_TRADE_PCT * 100,
                        result_r=-1.0,
                        entry_datetime=entry_dt,
                    )
                    embeds_to_send.append(embed)
                    trade_state.mark_update_posted(trade_id, "sl")

        tp_levels = [
            ("TP1", "tp1", trade.tp1, 1),
            ("TP2", "tp2", trade.tp2, 2),
            ("TP3", "tp3", trade.tp3, 3),
        ]

        if not progress["sl"]:
            risk = abs(entry - sl) if entry and sl else 1.0
            
            for label, flag, level, tp_num in tp_levels:
                if level is None or progress[flag]:
                    continue

                hit = False
                if direction == "bullish" and price >= level:
                    hit = True
                elif direction == "bearish" and price <= level:
                    hit = True
                
                if hit:
                    progress[flag] = True
                    
                    if not trade_state.is_update_posted(trade_id, flag):
                        if direction == "bullish":
                            rr = (level - entry) / risk if risk > 0 else 0
                        else:
                            rr = (entry - level) / risk if risk > 0 else 0
                        
                        realized_usd = risk_usd * rr
                        realized_pct = RISK_PER_TRADE_PCT * rr * 100
                        
                        remaining_pct = 100 - (tp_num * 33.3)
                        remaining_lots = lot_size * (remaining_pct / 100)
                        
                        entry_dt = TRADE_ENTRY_DATES.get(key)
                        embed = create_tp_hit_embed(
                            symbol=trade.symbol,
                            direction=direction,
                            tp_level=tp_num,
                            tp_price=level,
                            realized_usd=realized_usd,
                            realized_pct=realized_pct,
                            realized_r=rr,
                            remaining_pct=max(0, remaining_pct),
                            remaining_lots=max(0, remaining_lots),
                            current_sl=entry if tp_num == 1 else None,
                            moved_to_be=(tp_num == 1),
                            entry_datetime=entry_dt,
                        )
                        embeds_to_send.append(embed)
                        trade_state.mark_update_posted(trade_id, flag)

        all_tps_hit = all(
            progress[flag] for label, flag, level, _ in tp_levels if level is not None
        )

        if progress["sl"] or all_tps_hit:
            closed = True

        if closed:
            if progress["sl"]:
                pnl_usd = -risk_usd
                reason = "Stop Loss Hit"
            elif all_tps_hit:
                risk = abs(entry - sl) if entry and sl else 1.0
                total_rr = sum(
                    ((level - entry) / risk if direction == "bullish" else (entry - level) / risk)
                    for _, _, level, _ in tp_levels if level is not None
                ) / 3
                pnl_usd = risk_usd * total_rr
                reason = "All TPs Hit"
                
                if not trade_state.is_update_posted(trade_id, "closed"):
                    entry_dt = TRADE_ENTRY_DATES.get(key)
                    embed = create_trade_closed_embed(
                        symbol=trade.symbol,
                        direction=direction,
                        avg_exit=price,
                        total_result_usd=pnl_usd,
                        total_result_pct=RISK_PER_TRADE_PCT * total_rr * 100,
                        total_result_r=total_rr,
                        exit_reason=reason,
                        entry_datetime=entry_dt,
                    )
                    embeds_to_send.append(embed)
                    trade_state.mark_update_posted(trade_id, "closed")
            else:
                pnl_usd = 0
                reason = "Unknown"
            
            success, close_msg = close_trade_with_pnl(key, price, pnl_usd, reason)
            if success:
                print(f"[check_trade_updates] {trade.symbol}: {close_msg}")

        for embed in embeds_to_send:
            await updates_channel.send(embed=embed)


class BlueprintTraderBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("Slash commands synced!")


bot = BlueprintTraderBot()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("Blueprint Trader AI is online.")
    if os.getenv("OANDA_API_KEY"):
        if not autoscan_loop.is_running():
            autoscan_loop.start()
            print("Autoscan loop started.")
    else:
        print("OANDA_API_KEY not configured. Autoscan disabled. Set it in Replit Secrets to enable market scanning.")


@bot.tree.command(name="help", description="Show all available commands.")
async def help_command(interaction: discord.Interaction):
    commands_text = """
**Blueprint Trader AI - Commands**

**Scanning:**
`/scan [asset]` - Detailed scan of a single asset
`/forex` - Scan all forex pairs
`/crypto` - Scan crypto assets
`/com` - Scan commodities (metals + energies)
`/indices` - Scan stock indices
`/market` - Full market scan

**Trading:**
`/trade` - Show active trades with status
`/live` - Latest prices for all assets
`/cleartrades` - Clear all active trade tracking

**Analysis:**
`/backtest [asset] [period]` - Test strategy performance
  Example: `/backtest EUR_USD "Jan 2024 - Dec 2024"`
`/pass [month] [year]` - Simulate 10K challenge for a month
  Example: `/pass 9 2024`

**System:**
`/cache` - View cache statistics
`/clearcache` - Clear data cache
`/debug` - Bot health and status check
"""
    await interaction.response.send_message(commands_text, ephemeral=True)


@bot.tree.command(name="scan", description="Scan a single asset with full analysis.")
@app_commands.describe(asset="The asset symbol to scan (e.g., EUR_USD, BTC_USD)")
async def scan(interaction: discord.Interaction, asset: str):
    await interaction.response.defer()
    
    try:
        result = scan_single_asset(asset.upper().replace("/", "_"))

        if not result:
            await interaction.followup.send(f"No data available for **{asset}**. Check the instrument name.")
            return

        if result.confluence_score < 3:
            status_msg = (
                f"**{result.symbol}** | {result.direction.upper()}\n"
                f"Confluence: {result.confluence_score}/7\n\n"
                f"_Low confluence - no actionable setup at this time._"
            )
            await interaction.followup.send(status_msg)
            return

        msg = format_detailed_scan(result)
        chunks = split_message(msg, limit=1900)

        for i, chunk in enumerate(chunks):
            if i == 0:
                await interaction.followup.send(chunk)
            else:
                await interaction.followup.send(chunk)
    except Exception as e:
        print(f"[/scan] Error scanning {asset}: {e}")
        await interaction.followup.send(f"Error scanning **{asset}**: {str(e)}")


@bot.tree.command(name="forex", description="Scan all forex pairs.")
async def forex(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        scan_results, _ = await asyncio.to_thread(scan_forex)

        if not scan_results:
            await interaction.followup.send("**Forex** - No setups found.")
            return

        msg = format_scan_group("Forex", scan_results)
        chunks = split_message(msg, limit=1900)

        for chunk in chunks:
            await interaction.followup.send(chunk)
    except Exception as e:
        print(f"[/forex] Error: {e}")
        await interaction.followup.send(f"Error scanning forex: {str(e)}")


@bot.tree.command(name="crypto", description="Scan crypto assets.")
async def crypto(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        scan_results, _ = await asyncio.to_thread(scan_crypto)

        if not scan_results:
            await interaction.followup.send("**Crypto** - No setups found.")
            return

        msg = format_scan_group("Crypto", scan_results)
        chunks = split_message(msg, limit=1900)

        for chunk in chunks:
            await interaction.followup.send(chunk)
    except Exception as e:
        print(f"[/crypto] Error: {e}")
        await interaction.followup.send(f"Error scanning crypto: {str(e)}")


@bot.tree.command(name="com", description="Scan commodities (metals + energies).")
async def com(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        scan_results_m, _ = await asyncio.to_thread(scan_metals)
        scan_results_e, _ = await asyncio.to_thread(scan_energies)
        combined = scan_results_m + scan_results_e

        if not combined:
            await interaction.followup.send("**Commodities** - No setups found.")
            return

        msg = format_scan_group("Commodities", combined)
        chunks = split_message(msg, limit=1900)

        for chunk in chunks:
            await interaction.followup.send(chunk)
    except Exception as e:
        print(f"[/com] Error: {e}")
        await interaction.followup.send(f"Error scanning commodities: {str(e)}")


@bot.tree.command(name="indices", description="Scan stock indices.")
async def indices(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        scan_results, _ = await asyncio.to_thread(scan_indices)

        if not scan_results:
            await interaction.followup.send("**Indices** - No setups found.")
            return

        msg = format_scan_group("Indices", scan_results)
        chunks = split_message(msg, limit=1900)

        for chunk in chunks:
            await interaction.followup.send(chunk)
    except Exception as e:
        print(f"[/indices] Error: {e}")
        await interaction.followup.send(f"Error scanning indices: {str(e)}")


@bot.tree.command(name="market", description="Full market scan across all asset classes.")
async def market(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        markets = await asyncio.to_thread(scan_all_markets)

        messages = format_autoscan_output(markets)
        
        if not messages:
            await interaction.followup.send("**Market Scan** - No setups found.")
            return

        for msg in messages:
            chunks = split_message(msg, limit=1900)
            for chunk in chunks:
                await interaction.followup.send(chunk)
    except Exception as e:
        print(f"[/market] Error: {e}")
        await interaction.followup.send(f"Error scanning markets: {str(e)}")


@bot.tree.command(name="trade", description="Show active trades with status.")
async def trade(interaction: discord.Interaction):
    if not ACTIVE_TRADES:
        await interaction.response.send_message("No active trades being tracked.")
        return

    lines: list[str] = []
    lines.append("**Active Trades**")
    lines.append("")

    for key, t in ACTIVE_TRADES.items():
        emoji = "[BULL]" if t.direction == "bullish" else "[BEAR]"
        entry = t.entry if t.entry is not None else 0.0
        sl = t.stop_loss if t.stop_loss is not None else 0.0

        current_price, rr = _compute_trade_progress(t)
        rr_str = f"{rr:+.2f}R" if rr == rr else "N/A"

        lines.append(f"{emoji} **{t.symbol}** | {t.direction.upper()} | {t.confluence_score}/7")
        lines.append(f"   Entry: {entry:.5f} | SL: {sl:.5f} | Progress: {rr_str}")
        lines.append("")

    msg = "\n".join(lines)
    await interaction.response.send_message(msg[:2000])


def _format_price(price: float) -> str:
    """Format price with appropriate decimals: 4 for small prices, 2 for larger."""
    if price < 10:
        return f"{price:.4f}"
    else:
        return f"{price:.2f}"


@bot.tree.command(name="live", description="Show latest prices for all assets.")
async def live(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        groups = {
            "Forex": FOREX_PAIRS,
            "Metals": METALS,
            "Indices": INDICES,
            "Energies": ENERGIES,
            "Crypto": CRYPTO_ASSETS,
        }

        lines: list[str] = []
        lines.append("**Live Prices (Real-time)**")
        lines.append("")

        for name, symbols in groups.items():
            lines.append(f"**{name}**")
            if not symbols:
                lines.append("_No instruments configured._")
                lines.append("")
                continue

            prices = await asyncio.to_thread(get_current_prices, symbols)
            
            for sym in symbols:
                if sym in prices:
                    mid = prices[sym]["mid"]
                    lines.append(f"{sym}: `{_format_price(mid)}`")
                else:
                    lines.append(f"{sym}: N/A")
            lines.append("")

        msg = "\n".join(lines)
        chunks = split_message(msg, limit=1900)

        for chunk in chunks:
            await interaction.followup.send(chunk)
    except Exception as e:
        print(f"[/live] Error: {e}")
        await interaction.followup.send(f"Error fetching live prices: {str(e)}")


@bot.tree.command(name="backtest", description="Backtest strategy for period or yearly analysis")
@app_commands.describe(
    asset="The asset to backtest (e.g., EUR_USD)",
    period="YYYY for yearly, or date range (e.g., 'Jan 2024 - Dec 2024')"
)
async def backtest_cmd(interaction: discord.Interaction, asset: str, period: str):
    await interaction.response.defer()
    
    try:
        asset_clean = asset.upper().replace("/", "_")
        
        # Check if period is a single year for yearly analysis
        if period.strip().isdigit() and len(period.strip()) == 4:
            from backtest import run_yearly_backtest, validate_asset_performance
            year = int(period.strip())
            result = await asyncio.to_thread(run_yearly_backtest, asset_clean, year)
            
            # Format yearly results with validation
            lines = [
                f"**Yearly Backtest: {asset_clean} / {year}**",
                f"**Profile:** {result.get('profile_name', 'N/A')}",
                "",
                f"**Yearly Performance:**",
                f"  Trades: {result['total_trades']}",
                f"  Win Rate: {result['win_rate']:.1f}%",
                f"  Return: {result['net_return_pct']:+.1f}% (+${result['total_profit_usd']:,.0f})",
                f"  Avg Expectancy: {result['avg_rr']:+.2f}R/trade",
                "",
                f"**Validation (50+ trades, 70-100% WR):**",
                f"  {result['validation']['trade_count_reason']}",
                f"  {result['validation']['win_rate_reason']}",
                f"  {result['validation']['profitability_reason']}",
                f"  {result['validation']['expectancy_reason']}",
                "",
                f"**Status:** {'✓ APPROVED' if result['validation']['all_pass'] else '✗ NEEDS WORK'}",
                "",
                "**Monthly Breakdown:**",
            ]
            
            for month_result in result.get("monthly_results", []):
                lines.append(f"  {month_result['period']}: {month_result['total_trades']} trades, {month_result['win_rate']:.1f}% WR, {month_result['net_return_pct']:+.1f}%")
            
            msg = "\n".join(lines)
        else:
            # Single period backtest
            result = run_backtest(asset_clean, period)
            msg = format_backtest_result(result)
        
        chunks = split_message(msg, limit=1900)
        for chunk in chunks:
            await interaction.followup.send(chunk)
    except Exception as e:
        print(f"[/backtest] Error backtesting {asset}: {e}")
        await interaction.followup.send(f"Error running backtest for **{asset}**: {str(e)}")


@bot.tree.command(name="cache", description="View cache statistics.")
async def cache_cmd(interaction: discord.Interaction):
    stats = get_cache_stats()
    
    msg = (
        f"**Cache Statistics**\n\n"
        f"Cached Items: {stats['cached_items']}\n"
        f"Hit Rate: {stats['hit_rate_pct']}%\n"
        f"Hits: {stats['hits']} | Misses: {stats['misses']}"
    )
    await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="clearcache", description="Clear the data cache.")
async def clearcache(interaction: discord.Interaction):
    clear_cache()
    await interaction.response.send_message("Cache cleared successfully.", ephemeral=True)


@bot.tree.command(name="cleartrades", description="Clear all active trade tracking.")
async def cleartrades(interaction: discord.Interaction):
    count, message = clear_all_trades()
    await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(name="debug", description="Show bot health and status summary.")
async def debug_cmd(interaction: discord.Interaction):
    """Health and status check for the bot."""
    try:
        import platform
        from data import OANDA_API_KEY, OANDA_ACCOUNT_ID
        
        oanda_status = "Connected" if OANDA_API_KEY and OANDA_ACCOUNT_ID else "Not configured"
        
        cache_stats = get_cache_stats()
        
        autoscan_status = "Running" if autoscan_loop.is_running() else "Stopped"
        
        uptime_str = "N/A"
        if bot.user:
            uptime_str = f"Online as {bot.user.name}"
        
        scan_ch = bot.get_channel(SCAN_CHANNEL_ID)
        trades_ch = bot.get_channel(TRADES_CHANNEL_ID)
        updates_ch = bot.get_channel(TRADE_UPDATES_CHANNEL_ID)
        
        channels_status = []
        channels_status.append(f"Scan: {'OK' if scan_ch else 'NOT FOUND'}")
        channels_status.append(f"Trades: {'OK' if trades_ch else 'NOT FOUND'}")
        channels_status.append(f"Updates: {'OK' if updates_ch else 'NOT FOUND'}")
        
        profile = ACTIVE_ACCOUNT_PROFILE
        
        msg = (
            "**Blueprint Trader AI - Debug Info**\n\n"
            f"**Status:** {uptime_str}\n"
            f"**OANDA API:** {oanda_status}\n"
            f"**Autoscan:** {autoscan_status} (every {SCAN_INTERVAL_HOURS}H)\n"
            f"**Signal Mode:** {SIGNAL_MODE}\n\n"
            f"**Channels:**\n"
            f"  {' | '.join(channels_status)}\n\n"
            f"**Active Trades:** {len(ACTIVE_TRADES)}\n"
            f"**Cache:** {cache_stats['cached_items']} items, {cache_stats['hit_rate_pct']}% hit rate\n\n"
            f"**Account Profile:** {profile.display_name}\n"
            f"  Balance: ${profile.starting_balance:,.0f}\n"
            f"  Risk/Trade: {profile.risk_per_trade_pct*100:.1f}%\n"
            f"  Max Daily Loss: {profile.max_daily_loss_pct*100:.0f}%\n"
            f"  Max Total Loss: {profile.max_total_loss_pct*100:.0f}%\n"
            f"  Max Concurrent: {profile.max_concurrent_trades} trades\n"
            f"  Phase 1 Target: {profile.phases[0].profit_target_pct*100:.0f}%\n"
            f"  Phase 2 Target: {profile.phases[1].profit_target_pct*100:.0f}%\n\n"
            f"**System:** Python {platform.python_version()}"
        )
        
        await interaction.response.send_message(msg, ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Error getting debug info: {str(e)}", ephemeral=True)


@bot.tree.command(name="risk", description="Show current risk status and phase progress.")
async def risk_cmd(interaction: discord.Interaction):
    """Show risk status and challenge progress."""
    try:
        rm = get_risk_manager()
        summary = rm.get_risk_summary()
        phase_progress = summary.get("phase_progress", {})
        
        embed = create_phase_progress_embed(phase_progress, summary)
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"Error getting risk status: {str(e)}", ephemeral=True)


@bot.tree.command(name="profile", description="Show current account profile settings.")
async def profile_cmd(interaction: discord.Interaction):
    """Show active account profile details."""
    profile = ACTIVE_ACCOUNT_PROFILE
    
    lines = [
        f"**{profile.display_name}**",
        "",
        f"**Account:**",
        f"  Starting Balance: ${profile.starting_balance:,.0f}",
        f"  Currency: {profile.currency}",
        "",
        f"**Risk Settings:**",
        f"  Risk per Trade: {profile.risk_per_trade_pct*100:.1f}%",
        f"  Max Open Risk: {profile.max_open_risk_pct*100:.0f}%",
        f"  Max Concurrent Trades: {profile.max_concurrent_trades}",
        "",
        f"**Challenge Rules:**",
        f"  Max Daily Loss: {profile.max_daily_loss_pct*100:.0f}%",
        f"  Max Total Loss: {profile.max_total_loss_pct*100:.0f}%",
        "",
        f"**Phases:**",
    ]
    
    for i, phase in enumerate(profile.phases, 1):
        lines.append(
            f"  Phase {i}: {phase.profit_target_pct*100:.0f}% target, "
            f"{phase.min_profitable_days} profitable days"
        )
    
    lines.append("")
    lines.append(f"**Trading Restrictions:**")
    lines.append(f"  Friday Cutoff: {profile.friday_cutoff_hour_utc}:00 UTC")
    lines.append(f"  Monday Cooldown: {profile.monday_cooldown_hours}h")
    lines.append(f"  News Blackout: {profile.news_blackout_minutes} min")
    
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@bot.tree.command(name="pass", description="Simulate challenge for a specific month/year.")
@app_commands.describe(
    month="Month (1-12)",
    year="Year (e.g., 2024)"
)
async def pass_command(interaction: discord.Interaction, month: int, year: int):
    """Simulate a The5ers challenge for a given month/year."""
    if not 1 <= month <= 12:
        await interaction.response.send_message(
            "Invalid month. Please enter a value between 1 and 12.",
            ephemeral=True
        )
        return
    
    if not 2020 <= year <= 2030:
        await interaction.response.send_message(
            "Invalid year. Please enter a value between 2020 and 2030.",
            ephemeral=True
        )
        return
    
    await interaction.response.defer()
    
    try:
        result = await asyncio.to_thread(simulate_challenge_for_month, year, month)
        
        output = format_challenge_result(result)
        
        if result.both_passed:
            color = discord.Color.green()
            title = f"Challenge PASSED - {result.days_to_pass} Days"
        else:
            color = discord.Color.red()
            title = "Challenge FAILED"
        
        embed = discord.Embed(
            title=title,
            description=output,
            color=color,
        )
        
        await interaction.followup.send(embed=embed)
    except Exception as e:
        print(f"[/pass] Error simulating challenge: {e}")
        await interaction.followup.send(f"Error running challenge simulation: {str(e)}")


@bot.tree.command(name="output", description="Export trades from challenge with entry/exit dates for validation")
@app_commands.describe(
    month="Month (1-12)",
    year="Year (e.g., 2024 or 2025)"
)
async def output_command(interaction: discord.Interaction, month: int, year: int):
    """Export all trades from challenge simulation grouped by asset with entry/exit dates and prices."""
    if not 1 <= month <= 12:
        await interaction.response.send_message(
            "Invalid month. Please enter a value between 1 and 12.",
            ephemeral=True
        )
        return
    
    if not 2020 <= year <= 2030:
        await interaction.response.send_message(
            "Invalid year. Please enter a value between 2020 and 2030.",
            ephemeral=True
        )
        return
    
    await interaction.response.defer()
    
    try:
        result = await asyncio.to_thread(simulate_challenge_for_month, year, month)
        
        if not result.trades:
            await interaction.followup.send(f"No trades found for {calendar.month_name[month]} {year}.", ephemeral=True)
            return
        
        # Group trades by asset
        trades_by_asset = {}
        for trade in result.trades:
            asset = trade.get("asset", "UNKNOWN")
            if asset not in trades_by_asset:
                trades_by_asset[asset] = []
            trades_by_asset[asset].append(trade)
        
        # Format output by asset
        messages = []
        current_msg = f"**Trade Export: {calendar.month_name[month]} {year}**\n"
        current_msg += f"Total Trades: {len(result.trades)} | Period: {result.trading_days} trading days\n"
        current_msg += "=" * 50 + "\n\n"
        
        for asset in sorted(trades_by_asset.keys()):
            trades = trades_by_asset[asset]
            asset_msg = f"**{asset}** ({len(trades)} trades)\n"
            
            for i, trade in enumerate(trades, 1):
                entry_date = trade.get("entry_date", "N/A")
                entry_price = trade.get("entry", 0)
                direction = trade.get("direction", "?")
                sl = trade.get("sl", 0)
                tp1 = trade.get("tp1", 0)
                tp2 = trade.get("tp2", 0)
                tp3 = trade.get("tp3", 0)
                exit_date = trade.get("exit_date", "N/A")
                exit_reason = trade.get("exit_reason", "?")
                rr = trade.get("rr", 0)
                
                trade_line = (
                    f"{i}. [{entry_date}] {direction.upper()}\n"
                    f"   Entry: {entry_price:.5f} | SL: {sl:.5f}\n"
                    f"   TP1: {tp1:.5f} | TP2: {tp2:.5f} | TP3: {tp3:.5f}\n"
                    f"   Exit: {exit_reason} @ {exit_date} | R/R: {rr:+.2f}R\n\n"
                )
                
                if len(current_msg) + len(asset_msg) + len(trade_line) > 1900:
                    messages.append(current_msg + asset_msg)
                    current_msg = ""
                    asset_msg = f"**{asset}** (continued)\n"
                
                asset_msg += trade_line
            
            current_msg += asset_msg
        
        if current_msg.strip():
            messages.append(current_msg)
        
        # Send all messages
        for msg in messages:
            chunks = split_message(msg, limit=1900)
            for chunk in chunks:
                await interaction.followup.send(chunk)
    
    except Exception as e:
        print(f"[/output] Error exporting trades: {e}")
        await interaction.followup.send(f"Error exporting trades: {str(e)}", ephemeral=True)


@tasks.loop(hours=SCAN_INTERVAL_HOURS)
async def autoscan_loop():
    await bot.wait_until_ready()
    print("Running 4H autoscan...")
    
    clear_cache()

    scan_channel = bot.get_channel(SCAN_CHANNEL_ID)
    trades_channel = bot.get_channel(TRADES_CHANNEL_ID)

    if scan_channel is None:
        print("Scan channel not found.")
        return

    markets = await asyncio.to_thread(scan_all_markets)

    messages = format_autoscan_output(markets)
    for msg in messages:
        chunks = split_message(msg, limit=1900)
        for chunk in chunks:
            await scan_channel.send(chunk)

    if trades_channel is not None:
        active_trade_symbols = []
        pending_trades = []
        
        for group_name, (scan_results, trade_ideas) in markets.items():
            for trade in trade_ideas:
                if trade.status != "active":
                    continue
                trade_key = f"{trade.symbol}_{trade.direction}"
                if trade_key in ACTIVE_TRADES:
                    continue
                active_trade_symbols.append(trade.symbol)
                pending_trades.append(trade)
        
        live_prices = {}
        if active_trade_symbols:
            print(f"[autoscan] Fetching live prices for {len(active_trade_symbols)} symbols...")
            live_prices = await asyncio.to_thread(get_current_prices, list(set(active_trade_symbols)))
            print(f"[autoscan] Got live prices for {len(live_prices)} symbols")
        
        trade_state = get_trade_state()
        
        for trade in pending_trades:
            trade_key = f"{trade.symbol}_{trade.direction}"
            trade_id = trade_state.generate_trade_id(trade.symbol, trade.direction, trade.entry)
            
            if trade_state.is_trade_posted(trade_id):
                print(f"[autoscan] {trade.symbol}: SKIPPED - Already posted in previous session")
                continue
            
            live_price_data = live_prices.get(trade.symbol)
            if not live_price_data:
                print(f"[autoscan] {trade.symbol}: SKIPPED - Could not fetch live price (check OANDA API credentials)")
                continue
            
            live_mid = live_price_data.get("mid", 0)
            if live_mid <= 0:
                print(f"[autoscan] {trade.symbol}: SKIPPED - Live price invalid ({live_mid})")
                continue
            
            sizing = calculate_position_size_5ers(
                symbol=trade.symbol,
                entry_price=live_mid,
                stop_price=trade.stop_loss,
            )
            
            success, message = activate_trade(trade, live_mid, sizing)
            
            if not success:
                print(f"[autoscan] {trade.symbol}: BLOCKED by risk manager - {message}")
                blocked_embed = discord.Embed(
                    title=f"Trade Blocked: {trade.symbol}",
                    description=message,
                    color=discord.Color.orange(),
                )
                blocked_embed.add_field(name="Direction", value=trade.direction, inline=True)
                blocked_embed.add_field(name="Risk USD", value=f"${sizing.get('risk_usd', 0):.2f}", inline=True)
                await trades_channel.send(embed=blocked_embed)
                continue
            
            print(f"[autoscan] {trade.symbol}: Using live price {live_mid:.5f} as entry - {message}")

            confluence_items = build_confluence_list(trade)
            entry_time = TRADE_ENTRY_DATES.get(trade_key)
            
            embed = create_setup_embed(
                symbol=trade.symbol,
                direction=trade.direction,
                timeframe="H4",
                entry=trade.entry,
                stop_loss=trade.stop_loss,
                tp1=trade.tp1,
                tp2=trade.tp2,
                tp3=trade.tp3,
                confluence_score=trade.confluence_score,
                confluence_items=confluence_items,
                description=f"High-confluence setup with {trade.confluence_score}/7 factors aligned.",
                entry_datetime=entry_time,
            )
            
            if "Warning:" in message:
                embed.add_field(name="Risk Warning", value=message.split("Warning: ")[-1].rstrip(")"), inline=False)
            
            await trades_channel.send(embed=embed)
            
            trade_state.mark_trade_posted(trade_id)
        
        trade_state.update_scan_time()

    updates_channel = bot.get_channel(TRADE_UPDATES_CHANNEL_ID)
    if updates_channel is not None and ACTIVE_TRADES:
        await check_trade_updates(updates_channel)

    print("Autoscan finished.")


if not DISCORD_TOKEN:
    raise ValueError("DISCORD_BOT_TOKEN not found. Set it in Replit Secrets.")

bot.run(DISCORD_TOKEN)
