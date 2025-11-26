import discord
from discord.ext import tasks

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

from backtest import run_backtest
from data import get_ohlcv, get_cache_stats, clear_cache


ACTIVE_TRADES: dict[str, ScanResult] = {}
TRADE_PROGRESS: dict[str, dict[str, bool]] = {}


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

        events: list[str] = []
        closed = False

        if sl is not None and not progress["sl"]:
            if direction == "bullish" and price <= sl:
                progress["sl"] = True
                closed = True
                events.append(f"❌ **SL hit** at {price:.5f}")
            elif direction == "bearish" and price >= sl:
                progress["sl"] = True
                closed = True
                events.append(f"❌ **SL hit** at {price:.5f}")

        tp_levels = [
            ("TP1", "tp1", trade.tp1),
            ("TP2", "tp2", trade.tp2),
            ("TP3", "tp3", trade.tp3),
            ("TP4", "tp4", trade.tp4),
            ("TP5", "tp5", trade.tp5),
        ]

        if not progress["sl"]:
            for label, flag, level in tp_levels:
                if level is None or progress[flag]:
                    continue

                if direction == "bullish" and price >= level:
                    progress[flag] = True
                    events.append(f"✅ **{label} hit** at {price:.5f}")
                elif direction == "bearish" and price <= level:
                    progress[flag] = True
                    events.append(f"✅ **{label} hit** at {price:.5f}")

        if not events:
            continue

        emoji = "🟢" if direction == "bullish" else "🔴"
        lines: list[str] = []
        lines.append(f"🔔 **Trade Update**")
        lines.append(f"{emoji} {trade.symbol} | {direction.upper()}")
        if entry is not None:
            lines.append(f"Entry: {entry:.5f}")
        lines.extend(events)

        all_tps_hit = all(
            progress[flag] for label, flag, level in tp_levels if level is not None
        )

        if progress["sl"] or all_tps_hit:
            closed = True

        if closed:
            lines.append("📋 Trade closed.")
            ACTIVE_TRADES.pop(key, None)
            TRADE_PROGRESS.pop(key, None)

        await updates_channel.send("\n".join(lines)[:1900])


intents = discord.Intents.default()
intents.message_content = True

bot = discord.Bot(intents=intents)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print("Blueprint Trader AI is online.")
    if not autoscan_loop.is_running():
        autoscan_loop.start()


@bot.slash_command(description="Show all available commands.")
async def help(ctx: discord.ApplicationContext):
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
    await ctx.respond(commands_text, ephemeral=True)


@bot.slash_command(description="Scan a single asset with full analysis.")
async def scan(ctx: discord.ApplicationContext, asset: str):
    await ctx.defer()
    
    result = scan_single_asset(asset.upper().replace("/", "_"))

    if not result:
        await ctx.respond(f"❌ No data available for **{asset}**. Check the instrument name.")
        return

    if result.confluence_score < 3:
        status_msg = (
            f"📊 **{result.symbol}** | {result.direction.upper()}\n"
            f"Confluence: {result.confluence_score}/7\n\n"
            f"_Low confluence - no actionable setup at this time._"
        )
        await ctx.respond(status_msg)
        return

    msg = format_detailed_scan(result)
    chunks = split_message(msg, limit=1900)

    first = True
    for chunk in chunks:
        if first:
            await ctx.respond(chunk)
            first = False
        else:
            await ctx.followup.send(chunk)


@bot.slash_command(description="Scan all forex pairs.")
async def forex(ctx: discord.ApplicationContext):
    await ctx.defer()
    scan_results, _ = scan_forex()

    if not scan_results:
        await ctx.respond("📊 **Forex** - No setups found.")
        return

    msg = format_scan_group("Forex", scan_results)
    chunks = split_message(msg, limit=1900)

    first = True
    for chunk in chunks:
        if first:
            await ctx.respond(chunk)
            first = False
        else:
            await ctx.followup.send(chunk)


@bot.slash_command(description="Scan crypto assets.")
async def crypto(ctx: discord.ApplicationContext):
    await ctx.defer()
    scan_results, _ = scan_crypto()

    if not scan_results:
        await ctx.respond("📊 **Crypto** - No setups found.")
        return

    msg = format_scan_group("Crypto", scan_results)
    chunks = split_message(msg, limit=1900)

    first = True
    for chunk in chunks:
        if first:
            await ctx.respond(chunk)
            first = False
        else:
            await ctx.followup.send(chunk)


@bot.slash_command(description="Scan commodities (metals + energies).")
async def com(ctx: discord.ApplicationContext):
    await ctx.defer()
    scan_results_m, _ = scan_metals()
    scan_results_e, _ = scan_energies()
    combined = scan_results_m + scan_results_e

    if not combined:
        await ctx.respond("📊 **Commodities** - No setups found.")
        return

    msg = format_scan_group("Commodities", combined)
    chunks = split_message(msg, limit=1900)

    first = True
    for chunk in chunks:
        if first:
            await ctx.respond(chunk)
            first = False
        else:
            await ctx.followup.send(chunk)


@bot.slash_command(description="Scan stock indices.")
async def indices(ctx: discord.ApplicationContext):
    await ctx.defer()
    scan_results, _ = scan_indices()

    if not scan_results:
        await ctx.respond("📊 **Indices** - No setups found.")
        return

    msg = format_scan_group("Indices", scan_results)
    chunks = split_message(msg, limit=1900)

    first = True
    for chunk in chunks:
        if first:
            await ctx.respond(chunk)
            first = False
        else:
            await ctx.followup.send(chunk)


@bot.slash_command(description="Full market scan across all asset classes.")
async def market(ctx: discord.ApplicationContext):
    await ctx.defer()
    markets = scan_all_markets()

    messages = format_autoscan_output(markets)
    
    if not messages:
        await ctx.respond("📊 **Market Scan** - No setups found.")
        return

    first_message_sent = False
    for msg in messages:
        chunks = split_message(msg, limit=1900)
        for chunk in chunks:
            if not first_message_sent:
                await ctx.respond(chunk)
                first_message_sent = True
            else:
                await ctx.followup.send(chunk)


@bot.slash_command(description="Show active trades with status.")
async def trade(ctx: discord.ApplicationContext):
    if not ACTIVE_TRADES:
        await ctx.respond("📋 No active trades being tracked.")
        return

    lines: list[str] = []
    lines.append("📈 **Active Trades**")
    lines.append("")

    for key, t in ACTIVE_TRADES.items():
        emoji = "🟢" if t.direction == "bullish" else "🔴"
        entry = t.entry if t.entry is not None else 0.0
        sl = t.stop_loss if t.stop_loss is not None else 0.0

        current_price, rr = _compute_trade_progress(t)
        rr_str = f"{rr:+.2f}R" if rr == rr else "N/A"

        lines.append(f"{emoji} **{t.symbol}** | {t.direction.upper()} | {t.confluence_score}/7")
        lines.append(f"   Entry: {entry:.5f} | SL: {sl:.5f} | Progress: {rr_str}")
        lines.append("")

    msg = "\n".join(lines)
    await ctx.respond(msg[:2000])


@bot.slash_command(description="Show latest prices for all assets.")
async def live(ctx: discord.ApplicationContext):
    await ctx.defer()
    groups = {
        "Forex": FOREX_PAIRS,
        "Metals": METALS,
        "Indices": INDICES,
        "Energies": ENERGIES,
        "Crypto": CRYPTO_ASSETS,
    }

    lines: list[str] = []
    lines.append("📊 **Live Prices**")
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

    first = True
    for chunk in chunks:
        if first:
            await ctx.respond(chunk)
            first = False
        else:
            await ctx.followup.send(chunk)


@bot.slash_command(description='Backtest the strategy. Example: /backtest EUR_USD "Jan 2024 - Dec 2024"')
async def backtest(ctx: discord.ApplicationContext, asset: str, period: str):
    await ctx.defer()
    
    result = run_backtest(asset.upper().replace("/", "_"), period)

    msg = format_backtest_result(result)
    await ctx.respond(msg)


@bot.slash_command(description="View cache statistics.")
async def cache(ctx: discord.ApplicationContext):
    stats = get_cache_stats()
    
    msg = (
        f"📦 **Cache Statistics**\n\n"
        f"Cached Items: {stats['cached_items']}\n"
        f"Hit Rate: {stats['hit_rate_pct']}%\n"
        f"Hits: {stats['hits']} | Misses: {stats['misses']}"
    )
    await ctx.respond(msg, ephemeral=True)


@bot.slash_command(description="Clear the data cache.")
async def clearcache(ctx: discord.ApplicationContext):
    clear_cache()
    await ctx.respond("✅ Cache cleared successfully.", ephemeral=True)


@tasks.loop(hours=SCAN_INTERVAL_HOURS)
async def autoscan_loop():
    await bot.wait_until_ready()
    print("⏱️ Running 4H autoscan...")

    scan_channel = bot.get_channel(SCAN_CHANNEL_ID)
    trades_channel = bot.get_channel(TRADES_CHANNEL_ID)

    if scan_channel is None:
        print("❌ Scan channel not found.")
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

                emoji = "🟢" if trade.direction == "bullish" else "🔴"
                t_lines: list[str] = []
                t_lines.append(f"🎯 **New Trade Signal**")
                t_lines.append(f"{emoji} {trade.symbol} | {trade.direction.upper()}")
                t_lines.append(f"Confluence: {trade.confluence_score}/7")

                if trade.entry is not None and trade.stop_loss is not None:
                    t_lines.append(f"Entry: {trade.entry:.5f} | SL: {trade.stop_loss:.5f}")
                if trade.tp1 is not None:
                    t_lines.append(f"TP1: {trade.tp1:.5f} | TP2: {trade.tp2:.5f} | TP3: {trade.tp3:.5f}")

                await trades_channel.send("\n".join(t_lines)[:1900])

    updates_channel = bot.get_channel(TRADE_UPDATES_CHANNEL_ID)
    if updates_channel is not None and ACTIVE_TRADES:
        await check_trade_updates(updates_channel)

    print("✅ Autoscan finished.")


if not DISCORD_TOKEN:
    raise ValueError("DISCORD_BOT_TOKEN not found. Set it in Replit Secrets.")

bot.run(DISCORD_TOKEN)
