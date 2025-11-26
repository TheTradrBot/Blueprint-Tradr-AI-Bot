"""
Enhanced Discord formatting for Blueprint Trader AI.

Provides clean, comprehensive output for scan results with:
- Bullish/Bearish/Neutral status
- Confluence scores
- Setup types and what to look for
- Trade levels when available
"""

from __future__ import annotations

from typing import List, Optional
from strategy import ScanResult


def format_scan_summary(results: List[ScanResult]) -> str:
    """
    Format a list of scan results into a compact summary.
    Shows: Symbol | Direction | Confluence | Status | Key flags
    """
    if not results:
        return "No setups found."

    results = sorted(results, key=lambda r: (-r.confluence_score, r.symbol))
    
    lines: List[str] = []
    
    for res in results:
        direction_emoji = "🟢" if res.direction == "bullish" else "🔴" if res.direction == "bearish" else "⚪"
        
        status_tag = ""
        if res.status == "active":
            status_tag = "✅ ACTIVE"
        elif res.status == "in_progress":
            status_tag = "🕐 WATCHING"
        else:
            status_tag = "📊 SCAN"
        
        flags = []
        if "Y" in res.summary_reason.split("HTF=")[1][:1] if "HTF=" in res.summary_reason else False:
            flags.append("HTF")
        if "Y" in res.summary_reason.split("Loc=")[1][:1] if "Loc=" in res.summary_reason else False:
            flags.append("Loc")
        if "Y" in res.summary_reason.split("Fib=")[1][:1] if "Fib=" in res.summary_reason else False:
            flags.append("Fib")
        if "Y" in res.summary_reason.split("Liq=")[1][:1] if "Liq=" in res.summary_reason else False:
            flags.append("Liq")
        
        flag_str = ", ".join(flags) if flags else "-"
        
        line = f"{direction_emoji} **{res.symbol}** | {res.direction.upper()} | {res.confluence_score}/7 | {status_tag}"
        lines.append(line)
    
    return "\n".join(lines)


def format_scan_group(group_name: str, results: List[ScanResult]) -> str:
    """
    Format a group of scan results with header.
    Shows compact view for multiple instruments.
    """
    if not results:
        return f"📊 **{group_name}**\n_No setups found._"

    results = sorted(results, key=lambda r: (-r.confluence_score, r.symbol))

    lines: List[str] = []
    lines.append(f"📊 **{group_name} Scan**")
    lines.append("")
    
    active_count = sum(1 for r in results if r.status == "active")
    watching_count = sum(1 for r in results if r.status == "in_progress")
    
    if active_count > 0 or watching_count > 0:
        lines.append(f"🎯 {active_count} active | 🕐 {watching_count} watching")
        lines.append("")
    
    for res in results:
        direction_emoji = "🟢" if res.direction == "bullish" else "🔴"
        
        if res.status == "active":
            status = "✅"
        elif res.status == "in_progress":
            status = "🕐"
        else:
            status = "📊"
        
        htf = "✓" if "HTF trend alignment" in res.htf_bias or "HTF reversal" in res.htf_bias else "○"
        loc = "✓" if "score:" in res.location_note and int(res.location_note.split("score:")[1].split()[0]) >= 2 else "○"
        fib = "✓" if "retracement zone" in res.fib_note else "○"
        liq = "✓" if "sweep" in res.liquidity_note.lower() or "equal" in res.liquidity_note.lower() else "○"
        struct = "✓" if "bullish" in res.structure_note.lower() or "bearish" in res.structure_note.lower() else "○"
        conf = "✓" if "confirmed" in res.confirmation_note.lower() else "○"
        
        line = (
            f"{status} {direction_emoji} **{res.symbol}** "
            f"| {res.confluence_score}/7 "
            f"| HTF:{htf} Loc:{loc} Fib:{fib} Liq:{liq} Str:{struct} 4H:{conf}"
        )
        lines.append(line)
    
    return "\n".join(lines)


def format_detailed_scan(res: ScanResult) -> str:
    """
    Format a single scan result with full details.
    Used for /scan command response.
    """
    direction_emoji = "🟢" if res.direction == "bullish" else "🔴"
    
    if res.status == "active":
        status_line = "✅ **ACTIVE TRADE** - Entry signal confirmed"
    elif res.status == "in_progress":
        status_line = "🕐 **WATCHING** - Setup forming, waiting for confirmation"
    else:
        status_line = "📊 **SCAN ONLY** - No actionable setup yet"
    
    lines: List[str] = []
    lines.append(f"{direction_emoji} **{res.symbol}** | {res.direction.upper()}")
    lines.append(f"Confluence: **{res.confluence_score}/7**")
    lines.append(status_line)
    lines.append("")
    
    lines.append("**Analysis:**")
    
    htf_check = "✅" if "alignment" in res.htf_bias or "reversal" in res.htf_bias else "⚪"
    lines.append(f"{htf_check} HTF Bias: {_truncate(res.htf_bias, 80)}")
    
    loc_check = "✅" if "score:" in res.location_note and int(res.location_note.split("score:")[1].split()[0]) >= 2 else "⚪"
    lines.append(f"{loc_check} Location: {_truncate(res.location_note, 80)}")
    
    fib_check = "✅" if "retracement zone" in res.fib_note else "⚪"
    lines.append(f"{fib_check} Fibonacci: {_truncate(res.fib_note, 80)}")
    
    liq_check = "✅" if "sweep" in res.liquidity_note.lower() or "equal" in res.liquidity_note.lower() else "⚪"
    lines.append(f"{liq_check} Liquidity: {_truncate(res.liquidity_note, 80)}")
    
    struct_check = "✅" if res.structure_note and ("bullish" in res.structure_note.lower() or "bearish" in res.structure_note.lower()) else "⚪"
    lines.append(f"{struct_check} Structure: {_truncate(res.structure_note, 80)}")
    
    conf_check = "✅" if "confirmed" in res.confirmation_note.lower() else "⚪"
    lines.append(f"{conf_check} Confirmation: {_truncate(res.confirmation_note, 80)}")
    
    lines.append("")
    
    if res.status == "active" and res.entry is not None:
        lines.append("**Trade Levels:**")
        lines.append(f"• Entry: `{res.entry:.5f}`")
        lines.append(f"• Stop Loss: `{res.stop_loss:.5f}`")
        if res.tp1:
            lines.append(f"• TP1: `{res.tp1:.5f}` | TP2: `{res.tp2:.5f}` | TP3: `{res.tp3:.5f}`")
        lines.append("")
    
    if res.setup_type:
        lines.append(f"**Setup:** {res.setup_type}")
    
    if res.what_to_look_for:
        lines.append(f"**Watch For:** {res.what_to_look_for}")
    
    return "\n".join(lines)


def format_autoscan_output(markets: dict) -> List[str]:
    """
    Format autoscan results for Discord channels.
    Returns list of message strings.
    """
    messages: List[str] = []
    
    summary_lines = ["📊 **4H AUTOSCAN COMPLETE**", ""]
    
    total_active = 0
    total_watching = 0
    
    for group_name, (scan_results, trade_ideas) in markets.items():
        if not scan_results:
            continue
        
        active = sum(1 for r in scan_results if r.status == "active")
        watching = sum(1 for r in scan_results if r.status == "in_progress")
        total_active += active
        total_watching += watching
        
        status = ""
        if active > 0:
            status = f"🎯 {active} active"
        if watching > 0:
            status += f" 🕐 {watching} watching" if status else f"🕐 {watching} watching"
        if not status:
            status = "No setups"
        
        summary_lines.append(f"**{group_name}**: {status}")
    
    summary_lines.append("")
    summary_lines.append(f"**Total**: 🎯 {total_active} active | 🕐 {total_watching} watching")
    
    messages.append("\n".join(summary_lines))
    
    for group_name, (scan_results, _) in markets.items():
        active_setups = [r for r in scan_results if r.status == "active"]
        if active_setups:
            group_lines = [f"", f"**{group_name} - Active Setups:**"]
            for res in active_setups:
                emoji = "🟢" if res.direction == "bullish" else "🔴"
                group_lines.append(
                    f"{emoji} **{res.symbol}** {res.direction.upper()} | {res.confluence_score}/7"
                )
                if res.entry:
                    group_lines.append(
                        f"   Entry: {res.entry:.5f} | SL: {res.stop_loss:.5f}"
                    )
            messages.append("\n".join(group_lines))
    
    return messages


def format_trade_update(symbol: str, direction: str, event_type: str, price: float, level: float) -> str:
    """Format a trade update message."""
    emoji = "✅" if event_type.startswith("TP") else "❌"
    
    lines = [
        f"🔔 **Trade Update - {symbol}**",
        f"Direction: {direction.upper()}",
        f"{emoji} {event_type} hit at {price:.5f}",
        f"Level: {level:.5f}"
    ]
    
    return "\n".join(lines)


def format_backtest_result(result: dict) -> str:
    """Format backtest results for Discord with 5%ers 100K model."""
    asset = result.get("asset", "Unknown")
    period = result.get("period", "Unknown")
    total = result.get("total_trades", 0)
    win_rate = result.get("win_rate", 0.0)
    net_return = result.get("net_return_pct", 0.0)
    total_profit_usd = result.get("total_profit_usd", 0.0)
    max_drawdown_pct = result.get("max_drawdown_pct", 0.0)
    avg_rr = result.get("avg_rr", 0.0)
    account_size = result.get("account_size", 100000)
    
    tp1_trail = result.get("tp1_trail_hits", 0)
    tp2_count = result.get("tp2_hits", 0)
    tp3_count = result.get("tp3_hits", 0)
    sl_count = result.get("sl_hits", 0)
    
    profit_emoji = "📈" if total_profit_usd > 0 else "📉" if total_profit_usd < 0 else "➖"
    wr_emoji = "🎯" if win_rate >= 70 else "📊" if win_rate >= 50 else "⚠️"
    
    sign = "+" if total_profit_usd >= 0 else ""
    
    lines = [
        f"📊 **Backtest Results - {asset}**",
        f"Period: {period} | Account: ${account_size:,.0f} (5%ers High Stakes)",
        "",
        f"**Performance:**",
        f"{profit_emoji} Total Profit: **{sign}${total_profit_usd:,.0f}** ({sign}{net_return:.1f}%)",
        f"{wr_emoji} Win Rate: **{win_rate:.1f}%** ({total} trades)",
        f"📉 Max Drawdown: **{max_drawdown_pct:.1f}%**",
        f"📈 Expectancy: **{avg_rr:+.2f}R** / trade",
        "",
        f"**Exit Breakdown:**",
        f"• TP1+Trail: {tp1_trail} | TP2: {tp2_count} | TP3: {tp3_count}",
        f"• SL: {sl_count}",
    ]
    
    lines.append("")
    lines.append("_5%ers 100K Risk Model • 1% risk per trade_")
    
    return "\n".join(lines)


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max length."""
    if len(text) <= max_len:
        return text
    return text[:max_len-3] + "..."
