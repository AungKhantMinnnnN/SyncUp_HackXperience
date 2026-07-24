import discord
from discord import app_commands

from app.bot import embeds

# Placeholder in-memory catalogue until app/features/resources/service.py
# (backed by the real `resources` table) exists. Same shape the DB row will have.
_MOCK_CATALOGUE = [
    {"name": "Projector", "category": "AV", "quantity_total": 1, "exclusive": True},
    {"name": "Wireless mic", "category": "AV", "quantity_total": 4, "exclusive": False},
    {"name": "Folding chair", "category": "furniture", "quantity_total": 120, "exclusive": False},
    {"name": "Sign-in table", "category": "furniture", "quantity_total": 2, "exclusive": False},
    {"name": "Event banner", "category": "signage", "quantity_total": 3, "exclusive": False},
]


def register(tree: app_commands.CommandTree) -> None:
    @tree.command(name="inventory", description="List the org's tracked equipment and venues")
    async def inventory(interaction: discord.Interaction) -> None:
        embed = embeds.info_embed("Equipment inventory")
        for item in _MOCK_CATALOGUE:
            kind = "exclusive" if item["exclusive"] else "pooled"
            embed.add_field(
                name=item["name"],
                value=f"{item['quantity_total']} total · {kind} · {item['category']}",
                inline=True,
            )
        await interaction.response.send_message(embed=embed)

    @tree.command(
        name="packing-list",
        description="Preview an AI-generated packing list for an event description",
    )
    @app_commands.describe(description="Describe the event, e.g. '100-person orientation night'")
    async def packing_list(interaction: discord.Interaction, description: str) -> None:
        await interaction.response.defer(thinking=True)

        # Stub response so the command surface and embed shape are agreed on
        # before agent.py / availability.py exist. Swap this block for a call
        # to resources.service.plan_for_event() once that lands.
        mock_items = [
            {
                "name": "Projector",
                "quantity": 1,
                "available": False,
                "note": "Booked by Chess Club 7–9pm — alternatives suggested",
            },
            {"name": "Wireless mic", "quantity": 2, "available": True},
            {"name": "Folding chair", "quantity": 100, "available": True},
            {"name": "Sign-in table", "quantity": 1, "available": True},
        ]
        embed = embeds.packing_list_embed(description, mock_items)
        embed = embeds.conflict_field(
            embed,
            item_name="Projector",
            blocking_event="Chess Club meeting",
            alternative="AV desk has one spare unit",
        )
        await interaction.followup.send(embed=embed)
