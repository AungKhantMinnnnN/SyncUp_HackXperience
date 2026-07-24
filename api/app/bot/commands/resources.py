from datetime import UTC, datetime, timedelta
from uuid import UUID

import discord
from discord import app_commands
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import embeds
from app.config import settings
from app.db import with_session
from app.features.resources import service

# Placeholder in-memory catalogue for the two demo-safe commands below (/inventory,
# /packing-list), which stay mocked deliberately — see their docstrings. The newer
# commands (add-resource, availability, reservations, release) are real, DB-backed
# calls into features/resources/service.py.
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
        # Stays mocked on purpose: a demo-safe command that works even without a real
        # DATABASE_URL. Use /add-resource + a real Postgres to see live inventory.
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
        # Stub response: plan_for_event() needs a real Event row (created by scheduling
        # inside the confirm transaction). Keeps the command surface and embed shape
        # agreed on; swap for a real call once /plan produces events you can point at.
        await interaction.response.defer(thinking=True)

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

    @tree.command(name="add-resource", description="Add an item to the org's equipment catalogue")
    @app_commands.describe(
        name="Item name, e.g. 'Projector'",
        quantity="How many the org owns",
        category="Optional category, e.g. 'AV' or 'furniture'",
        exclusive="True if only one can be used at a time (a room, the one projector)",
    )
    async def add_resource(
        interaction: discord.Interaction,
        name: str,
        quantity: int,
        category: str | None = None,
        exclusive: bool = False,
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            resource = await with_session(
                service.add_resource, settings.org_id, name, quantity, category, exclusive
            )
        except Exception as exc:  # noqa: BLE001 — command boundary: any failure must still get a reply
            await interaction.followup.send(embed=embeds.error_embed("Couldn't add resource", str(exc)))
            return

        kind = "exclusive" if exclusive else "pooled"
        await interaction.followup.send(
            embed=embeds.success_embed(
                f"Added: {resource.name}",
                f"{quantity} total · {kind}" + (f" · {category}" if category else ""),
            )
        )

    @tree.command(name="availability", description="Check how much of a resource is free in a window")
    @app_commands.describe(
        name="Resource name, e.g. 'Projector'",
        hours_from_now="Window starts this many hours from now",
        duration_hours="How long the window lasts, in hours",
    )
    async def availability(
        interaction: discord.Interaction,
        name: str,
        hours_from_now: float,
        duration_hours: float,
    ) -> None:
        await interaction.response.defer(thinking=True)
        start = datetime.now(UTC) + timedelta(hours=hours_from_now)
        end = start + timedelta(hours=duration_hours)

        try:
            resource = await with_session(service.find_resource_by_name, settings.org_id, name)
            if resource is None:
                await interaction.followup.send(
                    embed=embeds.warning_embed("Not found", f"No resource named '{name}' in the catalogue.")
                )
                return

            total, reserved, free = await with_session(
                service.check_availability, settings.org_id, resource.id, start, end
            )
        except Exception as exc:  # noqa: BLE001 — command boundary: any failure must still get a reply
            await interaction.followup.send(embed=embeds.error_embed("Couldn't check availability", str(exc)))
            return

        embed = embeds.info_embed(
            f"Availability — {resource.name}",
            f"**{free}** of {total} free\n"
            f"{start:%b %d %H:%M} – {end:%b %d %H:%M} UTC\n"
            f"(reserved in window: {reserved})",
        )
        await interaction.followup.send(embed=embed)

    @tree.command(name="reservations", description="List active reservations for a resource")
    @app_commands.describe(name="Resource name, e.g. 'Projector'")
    async def reservations(interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            resource = await with_session(service.find_resource_by_name, settings.org_id, name)
            if resource is None:
                await interaction.followup.send(
                    embed=embeds.warning_embed("Not found", f"No resource named '{name}' in the catalogue.")
                )
                return

            rows = await with_session(service.list_reservations_for_resource, settings.org_id, resource.id)
        except Exception as exc:  # noqa: BLE001 — command boundary: any failure must still get a reply
            await interaction.followup.send(embed=embeds.error_embed("Couldn't list reservations", str(exc)))
            return

        if not rows:
            await interaction.followup.send(
                embed=embeds.info_embed(f"Reservations — {resource.name}", "None active.")
            )
            return

        embed = embeds.info_embed(f"Reservations — {resource.name}")
        for r in rows:
            embed.add_field(
                name=f"{r.start_utc:%b %d %H:%M} – {r.end_utc:%b %d %H:%M} UTC",
                value=f"qty {r.quantity} · {r.status} · id `{r.id}`",
                inline=False,
            )
        await interaction.followup.send(embed=embed)

    @tree.command(name="release", description="Release a held or confirmed reservation")
    @app_commands.describe(reservation_id="The reservation's UUID — see /reservations")
    async def release(interaction: discord.Interaction, reservation_id: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            rid = UUID(reservation_id)
        except ValueError:
            await interaction.followup.send(
                embed=embeds.error_embed("Invalid ID", f"'{reservation_id}' isn't a valid UUID.")
            )
            return

        try:
            released = await with_session(service.release_reservation, settings.org_id, rid)
        except service.InvalidTransitionError as exc:
            await interaction.followup.send(embed=embeds.error_embed("Can't release this reservation", str(exc)))
            return
        except Exception as exc:  # noqa: BLE001 — command boundary: any failure must still get a reply
            await interaction.followup.send(embed=embeds.error_embed("Couldn't release reservation", str(exc)))
            return

        if released:
            await interaction.followup.send(embed=embeds.success_embed("Reservation released"))
        else:
            await interaction.followup.send(
                embed=embeds.warning_embed("Not found", f"No reservation with ID `{reservation_id}` in this org.")
            )

    @tree.command(name="conflicts", description="Show resources that are short of what events requested")
    async def conflicts(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            rows = await with_session(service.list_conflicts, settings.org_id)
        except Exception as exc:  # noqa: BLE001 — command boundary: any failure must still get a reply
            await interaction.followup.send(embed=embeds.error_embed("Couldn't load conflicts", str(exc)))
            return

        if not rows:
            await interaction.followup.send(
                embed=embeds.success_embed("No conflicts", "Everything requested is fully reserved.")
            )
            return

        embed = embeds.warning_embed(f"{len(rows)} conflict(s)")
        for c in rows:
            embed = embeds.conflict_field(
                embed,
                item_name=f"{c.resource_name} (short {c.shortfall})",
                blocking_event=f"requested {c.requested}, has {c.available}",
                alternative=c.suggested_alternative,
            )
        await interaction.followup.send(embed=embed)

    @tree.command(name="confirm", description="Promote an event's held reservations to confirmed")
    @app_commands.describe(event_id="The event's UUID")
    async def confirm(interaction: discord.Interaction, event_id: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            eid = UUID(event_id)
        except ValueError:
            await interaction.followup.send(
                embed=embeds.error_embed("Invalid ID", f"'{event_id}' isn't a valid UUID.")
            )
            return

        async def _confirm_and_commit(db: AsyncSession) -> None:
            await service.confirm_for_event(db, eid)
            await db.commit()

        try:
            await with_session(_confirm_and_commit)
        except Exception as exc:  # noqa: BLE001 — command boundary: any failure must still get a reply
            await interaction.followup.send(embed=embeds.error_embed("Couldn't confirm", str(exc)))
            return

        await interaction.followup.send(embed=embeds.success_embed("Confirmed", f"Event `{event_id}` holds are now confirmed."))
