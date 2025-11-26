import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import (
    DISCORD_TOKEN,
    OANDA_API_KEY,
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
from data import get_ohlcv, get_cache_stats, clear_cache


ACTIVE_TRADES: dict[str, ScanResult] = {}
TRADE_PROGRESS: dict[str, dict[str, bool]] = {}
TRADE_SIZING: dict[str, dict] = {}


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


def _compute_trade_progress(idea: ScanResult) -> tuple[float, float]:
    """Compute (current_price, approx_RR) for a trade idea."""
    candles = get_ohlcv(idea.symbol, timeframe="D", count=1)
    if not candles:
        return float("nan"), float("nan")

    current_price = candles[-1]["close"]

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
    """Check active trades for TP/SL hits and send updates."""
    if not ACTIVE_TRADES:
        return

    trade_keys = list(ACTIVE_TRADES.keys())

    for key in trade_keys:
        trade = ACTIVE_TRADES.get(key)
        if trade is None:
            continue

        candles = get_ohlcv(trade.symbol, timeframe="H4", count=1)
        if not candles:
            candles = get_ohlcv(trade.symbol, timeframe="D", count=1)
        if not candles:
            continue

        price = candles[-1]["close"]
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

        if sl is not None and not progress["sl"]:
            if (direction == "bullish" and price <= sl) or (direction == "bearish" and price >= sl):
                progress["sl"] = True
                closed = True
                
                embed = create_sl_hit_embed(
                    symbol=trade.symbol,
                    direction=direction,
                    sl_price=sl,
                    result_usd=-risk_usd,
                    result_pct=-RISK_PER_TRADE_PCT * 100,
                    result_r=-1.0,
                )
                embeds_to_send.append(embed)

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
                    
                    if direction == "bullish":
                        rr = (level - entry) / risk if risk > 0 else 0
                    else:
                        rr = (entry - level) / risk if risk > 0 else 0
                    
                    realized_usd = risk_usd * rr
                    realized_pct = RISK_PER_TRADE_PCT * rr * 100
                    
                    remaining_pct = 100 - (tp_num * 33.3)
                    remaining_lots = lot_size * (remaining_pct / 100)
                    
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
                    )
                    embeds_to_send.append(embed)

        all_tps_hit = all(
            progress[flag] for label, flag, level, _ in tp_levels if level is not None
        )

        if progress["sl"] or all_tps_hit:
            closed = True

        if closed:
            if all_tps_hit and not progress["sl"]:
                risk = abs(entry - sl) if entry and sl else 1.0
                total_rr = sum(
                    ((level - entry) / risk if direction == "bullish" else (entry - level) / risk)
                    for _, _, level, _ in tp_levels if level is not None
                ) / 3
                
                embed = create_trade_closed_embed(
                    symbol=trade.symbol,
                    direction=direction,
                    avg_exit=price,
                    total_result_usd=risk_usd * total_rr,
                    total_result_pct=RISK_PER_TRADE_PCT * total_rr * 100,
                    total_result_r=total_rr,
                    exit_reason="All TPs Hit",
                )
                embeds_to_send.append(embed)
            
            ACTIVE_TRADES.pop(key, None)
            TRADE_PROGRESS.pop(key, None)
            TRADE_SIZING.pop(key, None)

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
    if OANDA_API_KEY:
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

**Analysis:**
`/backtest [asset] [period]` - Test strategy performance
  Example: `/backtest EUR_USD "Jan 2024 - Dec 2024"`

**System:**
`/cache` - View cache statistics
`/clearcache` - Clear data cache
"""
    await interaction.response.send_message(commands_text, ephemeral=True)


@bot.tree.command(name="scan", description="Scan a single asset with full analysis.")
@app_commands.describe(asset="The asset symbol to scan (e.g., EUR_USD, BTC_USD)")
async def scan(interaction: discord.Interaction, asset: str):
    await interaction.response.defer()
    
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


@bot.tree.command(name="forex", description="Scan all forex pairs.")
async def forex(interaction: discord.Interaction):
    await interaction.response.defer()
    scan_results, _ = scan_forex()

    if not scan_results:
        await interaction.followup.send("**Forex** - No setups found.")
        return

    msg = format_scan_group("Forex", scan_results)
    chunks = split_message(msg, limit=1900)

    for chunk in chunks:
        await interaction.followup.send(chunk)


@bot.tree.command(name="crypto", description="Scan crypto assets.")
async def crypto(interaction: discord.Interaction):
    await interaction.response.defer()
    scan_results, _ = scan_crypto()

    if not scan_results:
        await interaction.followup.send("**Crypto** - No setups found.")
        return

    msg = format_scan_group("Crypto", scan_results)
    chunks = split_message(msg, limit=1900)

    for chunk in chunks:
        await interaction.followup.send(chunk)


@bot.tree.command(name="com", description="Scan commodities (metals + energies).")
async def com(interaction: discord.Interaction):
    await interaction.response.defer()
    scan_results_m, _ = scan_metals()
    scan_results_e, _ = scan_energies()
    combined = scan_results_m + scan_results_e

    if not combined:
        await interaction.followup.send("**Commodities** - No setups found.")
        return

    msg = format_scan_group("Commodities", combined)
    chunks = split_message(msg, limit=1900)

    for chunk in chunks:
        await interaction.followup.send(chunk)


@bot.tree.command(name="indices", description="Scan stock indices.")
async def indices(interaction: discord.Interaction):
    await interaction.response.defer()
    scan_results, _ = scan_indices()

    if not scan_results:
        await interaction.followup.send("**Indices** - No setups found.")
        return

    msg = format_scan_group("Indices", scan_results)
    chunks = split_message(msg, limit=1900)

    for chunk in chunks:
        await interaction.followup.send(chunk)


@bot.tree.command(name="market", description="Full market scan across all asset classes.")
async def market(interaction: discord.Interaction):
    await interaction.response.defer()
    markets = scan_all_markets()

    messages = format_autoscan_output(markets)
    
    if not messages:
        await interaction.followup.send("**Market Scan** - No setups found.")
        return

    for msg in messages:
        chunks = split_message(msg, limit=1900)
        for chunk in chunks:
            await interaction.followup.send(chunk)


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


@bot.tree.command(name="live", description="Show latest prices for all assets.")
async def live(interaction: discord.Interaction):
    await interaction.response.defer()
    groups = {
        "Forex": FOREX_PAIRS,
        "Metals": METALS,
        "Indices": INDICES,
        "Energies": ENERGIES,
        "Crypto": CRYPTO_ASSETS,
    }

    lines: list[str] = []
    lines.append("**Live Prices**")
    lines.append("")

    for name, symbols in groups.items():
        lines.append(f"**{name}**")
        if not symbols:
            lines.append("_No instruments configured._")
            lines.append("")
            continue

        for sym in symbols:
            candles = get_ohlcv(sym, timeframe="D", count=1)
            if not candles:
                lines.append(f"{sym}: N/A")
            else:
                price = candles[-1]["close"]
                lines.append(f"{sym}: `{price:.5f}`")
        lines.append("")

    msg = "\n".join(lines)
    chunks = split_message(msg, limit=1900)

    for chunk in chunks:
        await interaction.followup.send(chunk)


@bot.tree.command(name="backtest", description='Backtest the strategy. Example: /backtest EUR_USD "Jan 2024 - Dec 2024"')
@app_commands.describe(
    asset="The asset to backtest (e.g., EUR_USD)",
    period="The time period (e.g., 'Jan 2024 - Dec 2024')"
)
async def backtest_cmd(interaction: discord.Interaction, asset: str, period: str):
    await interaction.response.defer()
    
    result = run_backtest(asset.upper().replace("/", "_"), period)

    msg = format_backtest_result(result)
    await interaction.followup.send(msg)


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


@tasks.loop(hours=SCAN_INTERVAL_HOURS)
async def autoscan_loop():
    await bot.wait_until_ready()
    print("Running 4H autoscan...")

    scan_channel = bot.get_channel(SCAN_CHANNEL_ID)
    trades_channel = bot.get_channel(TRADES_CHANNEL_ID)

    if scan_channel is None:
        print("Scan channel not found.")
        return

    markets = scan_all_markets()

    messages = format_autoscan_output(markets)
    for msg in messages:
        chunks = split_message(msg, limit=1900)
        for chunk in chunks:
            await scan_channel.send(chunk)

    if trades_channel is not None:
        for group_name, (scan_results, trade_ideas) in markets.items():
            for trade in trade_ideas:
                if trade.status != "active":
                    continue

                trade_key = f"{trade.symbol}_{trade.direction}"
                if trade_key in ACTIVE_TRADES:
                    continue

                ACTIVE_TRADES[trade_key] = trade
                _ensure_trade_progress(trade_key)

                confluence_items = build_confluence_list(trade)
                
                sizing = calculate_position_size_5ers(
                    symbol=trade.symbol,
                    entry_price=trade.entry,
                    stop_price=trade.stop_loss,
                )
                
                TRADE_SIZING[trade_key] = sizing
                
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
                )
                
                await trades_channel.send(embed=embed)

    updates_channel = bot.get_channel(TRADE_UPDATES_CHANNEL_ID)
    if updates_channel is not None and ACTIVE_TRADES:
        await check_trade_updates(updates_channel)

    print("Autoscan finished.")


if not DISCORD_TOKEN:
    raise ValueError("DISCORD_BOT_TOKEN not found. Set it in Replit Secrets.")

bot.run(DISCORD_TOKEN)
