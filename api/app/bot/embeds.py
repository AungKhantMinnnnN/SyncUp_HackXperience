import discord

BRAND_COLOR = 0xC8102E
SUCCESS_COLOR = 0x2E7D4F
WARNING_COLOR = 0xB8860B
ERROR_COLOR = 0x8B0000

FOOTER_TEXT = "SyncUp"


def _base_embed(title: str, description: str | None, color: int) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def info_embed(title: str, description: str | None = None) -> discord.Embed:
    return _base_embed(title, description, BRAND_COLOR)


def success_embed(title: str, description: str | None = None) -> discord.Embed:
    return _base_embed(title, description, SUCCESS_COLOR)


def warning_embed(title: str, description: str | None = None) -> discord.Embed:
    return _base_embed(title, description, WARNING_COLOR)


def error_embed(title: str, description: str | None = None) -> discord.Embed:
    return _base_embed(title, description, ERROR_COLOR)


def conflict_field(
    embed: discord.Embed,
    *,
    item_name: str,
    blocking_event: str,
    alternative: str | None = None,
) -> discord.Embed:
    value = f"Already booked for **{blocking_event}**"
    if alternative:
        value += f"\nSuggested alternative: {alternative}"
    embed.add_field(name=f"⚠️ {item_name}", value=value, inline=False)
    return embed


def packing_list_embed(event_title: str, items: list[dict]) -> discord.Embed:
    """items: [{"name": str, "quantity": int, "available": bool, "note": str | None}]"""
    embed = info_embed(f"Packing list — {event_title}")
    for item in items:
        status = "✅" if item["available"] else "⚠️"
        line = f"{status} x{item['quantity']}"
        if item.get("note"):
            line += f" — {item['note']}"
        embed.add_field(name=item["name"], value=line, inline=True)
    return embed

_VERDICT_COLOR = {"OK": SUCCESS_COLOR, "TIGHT": WARNING_COLOR, "OVER": ERROR_COLOR}


def budget_embed(
    *,
    title: str,
    lines: list,  # BudgetLineItem rows — category, description, unit_cost, quantity, line_total
    estimated_total,
    verdict: str,
    stated_cap=None,
    remaining=None,
    suggested_cuts: list[str] | None = None,
) -> discord.Embed:
    embed = discord.Embed(title=title, color=_VERDICT_COLOR.get(verdict, BRAND_COLOR))
    embed.set_footer(text=FOOTER_TEXT)

    for l in lines:
        label = l.description or l.category
        embed.add_field(
            name=f"{l.category} — {label}" if l.description else l.category,
            value=f"${l.unit_cost} × {l.quantity} = **${l.line_total}**",
            inline=False,
        )

    summary = f"**Estimated total:** ${estimated_total}\n**Verdict:** {verdict}"
    if stated_cap is not None:
        summary += f"\n**Stated cap:** ${stated_cap}"
    if remaining is not None:
        summary += f"\n**Semester remaining after this event:** ${remaining}"
    embed.add_field(name="Summary", value=summary, inline=False)

    if suggested_cuts:
        embed.add_field(
            name="Suggested cuts",
            value="\n".join(f"• {c}" for c in suggested_cuts),
            inline=False,
        )

    return embed