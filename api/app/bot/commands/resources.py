from datetime import UTC, datetime, timedelta
from uuid import UUID

import discord
from discord import app_commands
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import embeds
from app.config import settings
from app.db import with_session
from app.features.resources import service

def register(tree: app_commands.CommandTree) -> None:
    @tree.command(name="inventory", description="List the org's tracked equipment")
    async def inventory(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            resources = await with_session(service.list_catalogue, settings.org_id)
        except Exception as exc:  # noqa: BLE001 — command boundary: always reply
            await interaction.followup.send(embed=embeds.error_embed("Couldn't load inventory", str(exc)))
            return

        if not resources:
            await interaction.followup.send(
                embed=embeds.info_embed("Equipment inventory", "Nothing yet — add one with /add-resource.")
            )
            return

        embed = embeds.info_embed("Equipment inventory")
        for r in resources:
            kind = "exclusive" if r.exclusive else "pooled"
            embed.add_field(
                name=r.name,
                value=f"{r.quantity_total} total · {kind} · {r.category or 'uncategorized'}",
                inline=True,
            )
        await interaction.followup.send(embed=embed)

    @tree.command(
        name="packing-list",
        description="Generate the AI packing list for a confirmed event",
    )
    @app_commands.describe(event_id="The event's UUID (from a /plan confirmation)")
    async def packing_list(interaction: discord.Interaction, event_id: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            eid = UUID(event_id)
        except ValueError:
            await interaction.followup.send(
                embed=embeds.error_embed("Invalid ID", f"'{event_id}' isn't a valid UUID.")
            )
            return

        # Real generation against the org's seeded catalogue: infer -> hold -> persist,
        # then read back the actual packing_list_items. Commits its own transaction
        # (nothing wraps it here, unlike scheduling's confirm).
        async def _generate(db: AsyncSession):
            event = await service.load_event_view(db, eid)
            if event is None or event.org_id != settings.org_id:
                return None
            plan = await service.plan_for_event(db, event)
            await db.commit()
            items = await service.list_packing_list_items(db, eid)
            return event.title, plan, items

        try:
            result = await with_session(_generate)
        except Exception as exc:  # noqa: BLE001 — command boundary: always reply
            await interaction.followup.send(embed=embeds.error_embed("Couldn't build packing list", str(exc)))
            return

        if result is None:
            await interaction.followup.send(
                embed=embeds.warning_embed("Event not found", f"No event `{event_id}` in this org.")
            )
            return

        title, plan, items = result
        if not items:
            await interaction.followup.send(
                embed=embeds.warning_embed(
                    "Empty packing list", "The planner returned no items — check Foundry config / server logs."
                )
            )
            return

        embed = embeds.info_embed(f"Packing list — {title}")
        for it in items:
            tag = "✅ owned" if it.org_owned else "🛒 to buy"
            cost = f" · ${it.est_cost}" if it.est_cost is not None else ""
            embed.add_field(name=it.item_name, value=f"x{it.quantity} · {tag}{cost}", inline=True)
        for c in plan.conflicts:
            embed = embeds.conflict_field(
                embed,
                item_name=f"{c.resource_name} (short {c.shortfall})",
                blocking_event=f"requested {c.requested}, has {c.available}",
                alternative=c.suggested_alternative,
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
                item_name=f"{c.resource_name} — short {c.shortfall} (need {c.requested}, have {c.available})",
                blocking_event=c.blocking_event_title or "another reservation",
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
