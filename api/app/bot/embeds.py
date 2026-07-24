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
