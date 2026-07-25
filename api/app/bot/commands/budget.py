"""Discord slash commands for finance (Member C). Calls features/finance/service.py
directly, in-process — no HTTP round trip to router.py. Follows the same pattern as
commands/resources.py: with_session() for DB access, defer() first, error_embed on
any failure.
"""

from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import discord
from discord import app_commands
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import embeds
from app.config import settings
from app.core.time import now_utc
from app.db import with_session
from app.features.finance import service
from app.features.scheduling import service as sched


async def _member_id_for_discord_user(db: AsyncSession, discord_user_id: int) -> UUID | None:
    row = (
        await db.execute(
            text("SELECT id FROM members WHERE discord_user_id = :did"),
            {"did": str(discord_user_id)},
        )
    ).first()
    return row.id if row is not None else None


# --- Autocomplete: pick an event / budget by name; the UUID is the hidden value ------


async def _event_choices(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    now = now_utc()
    try:
        events = await with_session(
            sched.list_events, now - timedelta(days=7), now + timedelta(days=30)
        )
    except Exception:  # noqa: BLE001 — autocomplete must never raise
        return []
    cur = current.lower()
    out = []
    for e in events:
        label = f"{e.title} · {e.start_utc:%d %b}"
        if cur in label.lower():
            out.append(app_commands.Choice(name=label[:100], value=str(e.id)))
    return out[:25]


async def _budget_choices(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    try:
        rows = await with_session(service.list_event_budgets, settings.org_id)
    except Exception:  # noqa: BLE001
        return []
    cur = current.lower()
    out = []
    for r in rows:
        label = f"{r['title']} — est ${r['estimated_total']} ({r['status']})"
        if cur in label.lower():
            out.append(app_commands.Choice(name=label[:100], value=str(r["id"])))
    return out[:25]


def register(tree: app_commands.CommandTree) -> None:
    budget_group = app_commands.Group(name="budget", description="Budget drafting and approval")

    @budget_group.command(name="draft", description="Show or draft an event's itemized budget")
    @app_commands.describe(event="Pick the event (type to search)")
    @app_commands.autocomplete(event=_event_choices)
    async def budget_draft(interaction: discord.Interaction, event: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            eid = UUID(event)
        except ValueError:
            await interaction.followup.send(
                embed=embeds.error_embed("Invalid selection", "Pick an event from the list.")
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
            title="Budget draft",
            lines=lines,
            estimated_total=eb.estimated_total,
            verdict=verdict,
            stated_cap=eb.stated_cap,
            remaining=remaining,
            suggested_cuts=suggested_cuts,
        )
        await interaction.followup.send(embed=embed)

    @budget_group.command(name="approve", description="Approve a drafted event budget")
    @app_commands.describe(budget="Pick the event budget to approve")
    @app_commands.autocomplete(budget=_budget_choices)
    async def budget_approve(interaction: discord.Interaction, budget: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            bid = UUID(budget)
        except ValueError:
            await interaction.followup.send(
                embed=embeds.error_embed("Invalid selection", "Pick a budget from the list.")
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
                f"Now **approved** — ${eb.estimated_total} committed against the semester allocation.",
            )
        )

    tree.add_command(budget_group)

    @tree.command(name="expense", description="Log an actual expense against a budget")
    @app_commands.describe(
        budget="Pick the event budget",
        amount="Amount spent, e.g. 42.50",
        description="What this expense was for",
    )
    @app_commands.autocomplete(budget=_budget_choices)
    async def expense(
        interaction: discord.Interaction, budget: str, amount: float, description: str
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            bid = UUID(budget)
        except ValueError:
            await interaction.followup.send(
                embed=embeds.error_embed("Invalid selection", "Pick a budget from the list.")
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