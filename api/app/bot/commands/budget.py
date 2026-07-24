"""Discord slash commands for finance (Member C). Calls features/finance/service.py
directly, in-process — no HTTP round trip to router.py. Follows the same pattern as
commands/resources.py: with_session() for DB access, defer() first, error_embed on
any failure.
"""

from decimal import Decimal
from uuid import UUID

import discord
from discord import app_commands
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import embeds
from app.db import with_session
from app.features.finance import service


async def _member_id_for_discord_user(db: AsyncSession, discord_user_id: int) -> UUID | None:
    row = (
        await db.execute(
            text("SELECT id FROM members WHERE discord_user_id = :did"),
            {"did": str(discord_user_id)},
        )
    ).first()
    return row.id if row is not None else None


def register(tree: app_commands.CommandTree) -> None:
    budget_group = app_commands.Group(name="budget", description="Budget drafting and approval")

    @budget_group.command(name="draft", description="Show or draft an event's itemized budget")
    @app_commands.describe(event_id="The event's UUID")
    async def budget_draft(interaction: discord.Interaction, event_id: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            eid = UUID(event_id)
        except ValueError:
            await interaction.followup.send(
                embed=embeds.error_embed("Invalid ID", f"'{event_id}' isn't a valid UUID.")
            )
            return

        async def _load(db: AsyncSession):
            existing = await service.get_event_budget(db, eid)
            if existing is not None:
                eb, lines = existing
                result = await service.get_verdict(db, eb)
                return eb, lines, result.verdict, result.remaining, None
            # No draft yet — trigger the full drafting flow (owns its own commit).
            draft = await service.regenerate(db, eid)
            return draft.event_budget, draft.lines, draft.verdict, draft.remaining, draft.suggested_cuts

        try:
            eb, lines, verdict, remaining, suggested_cuts = await with_session(_load)
        except LookupError as exc:
            await interaction.followup.send(embed=embeds.error_embed("Not found", str(exc)))
            return
        except Exception as exc:  # noqa: BLE001 — command boundary: any failure must still get a reply
            await interaction.followup.send(embed=embeds.error_embed("Couldn't draft budget", str(exc)))
            return

        embed = embeds.budget_embed(
            title=f"Budget — event {event_id[:8]}",
            lines=lines,
            estimated_total=eb.estimated_total,
            verdict=verdict,
            stated_cap=eb.stated_cap,
            remaining=remaining,
            suggested_cuts=suggested_cuts,
        )
        embed.add_field(name="Budget ID", value=f"`{eb.id}`", inline=False)
        await interaction.followup.send(embed=embed)

    @budget_group.command(name="approve", description="Approve a drafted event budget")
    @app_commands.describe(budget_id="The event_budget UUID (from /budget draft)")
    async def budget_approve(interaction: discord.Interaction, budget_id: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            bid = UUID(budget_id)
        except ValueError:
            await interaction.followup.send(
                embed=embeds.error_embed("Invalid ID", f"'{budget_id}' isn't a valid UUID.")
            )
            return

        async def _approve(db: AsyncSession):
            actor_id = await _member_id_for_discord_user(db, interaction.user.id)
            if actor_id is None:
                raise LookupError("Your Discord account isn't linked to a member record yet.")
            return await service.approve(db, bid, actor_id)

        try:
            eb = await with_session(_approve)
        except LookupError as exc:
            await interaction.followup.send(embed=embeds.error_embed("Couldn't approve", str(exc)))
            return
        except service.InvalidBudgetStatus as exc:
            await interaction.followup.send(embed=embeds.error_embed("Can't approve", str(exc)))
            return
        except Exception as exc:  # noqa: BLE001
            await interaction.followup.send(embed=embeds.error_embed("Couldn't approve", str(exc)))
            return

        await interaction.followup.send(
            embed=embeds.success_embed(
                "Budget approved",
                f"`{eb.id}` is now **approved** — ${eb.estimated_total} committed against the semester allocation.",
            )
        )

    tree.add_command(budget_group)

    @tree.command(name="expense", description="Log an actual expense against a budget")
    @app_commands.describe(
        budget_id="The event_budget UUID",
        amount="Amount spent, e.g. 42.50",
        description="What this expense was for",
    )
    async def expense(
        interaction: discord.Interaction, budget_id: str, amount: float, description: str
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            bid = UUID(budget_id)
        except ValueError:
            await interaction.followup.send(
                embed=embeds.error_embed("Invalid ID", f"'{budget_id}' isn't a valid UUID.")
            )
            return

        amount_dec = Decimal(str(amount)).quantize(Decimal("0.01"))  # str() avoids float binary noise

        async def _log(db: AsyncSession):
            member_id = await _member_id_for_discord_user(db, interaction.user.id)
            if member_id is None:
                raise LookupError("Your Discord account isn't linked to a member record yet.")
            return await service.log_expense(db, bid, amount_dec, description, member_id)

        try:
            exp = await with_session(_log)
        except LookupError as exc:
            await interaction.followup.send(embed=embeds.error_embed("Couldn't log expense", str(exc)))
            return
        except Exception as exc:  # noqa: BLE001
            await interaction.followup.send(embed=embeds.error_embed("Couldn't log expense", str(exc)))
            return

        variance_line = ""
        if exp.variance is not None:
            sign = "over" if exp.variance > 0 else "under"
            variance_line = f"\n**Variance:** ${abs(exp.variance)} {sign} estimate"

        await interaction.followup.send(
            embed=embeds.success_embed("Expense logged", f"${amount_dec} — {description}{variance_line}")
        )