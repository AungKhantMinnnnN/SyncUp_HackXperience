"""/plan — thin Discord adapter over scheduling.service (the same functions the REST
routes call). Never a second implementation. Defers immediately (LLM round trip > 3s)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands

from app.bot import embeds
from app.db import with_session
from app.features.scheduling import service

_FALLBACK_TZ = ZoneInfo("UTC")  # used only if the org row has no valid timezone


def _fmt(dt, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%a %d %b · %I:%M %p")


def _window_line(req, tz: ZoneInfo) -> str:
    """Show the window the LLM parsed, so an empty result is debuggable at a glance."""
    pc = (req.parsed_constraints or {}) if req else {}
    try:
        s = datetime.fromisoformat(pc["window_start"])
        e = datetime.fromisoformat(pc["window_end"])
        return f"\n\n**Searched:** {_fmt(s, tz)} – {_fmt(e, tz)}"
    except (KeyError, TypeError, ValueError):
        return ""


class _ConfirmButton(discord.ui.Button):
    def __init__(self, proposal, tz: ZoneInfo) -> None:
        super().__init__(label=_fmt(proposal.start_utc, tz), style=discord.ButtonStyle.primary)
        self.proposal_id = proposal.id
        self.tz = tz

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            plan = await with_session(service.confirm_proposal, self.proposal_id, None)
        except service.AlreadyConfirmed:
            await interaction.followup.send(
                embed=embeds.warning_embed("Already confirmed", "That slot is taken."),
                ephemeral=True,
            )
            return
        embed = embeds.success_embed("Event confirmed", plan.event.title)
        embed.add_field(name="When", value=_fmt(plan.event.start_utc, self.tz), inline=False)
        embed.add_field(name="Budget", value=plan.budget.verdict, inline=True)
        await interaction.edit_original_response(embed=embed, view=None)


class _ProposalView(discord.ui.View):
    def __init__(self, proposals, tz: ZoneInfo) -> None:
        super().__init__(timeout=300)
        for p in proposals[:5]:
            self.add_item(_ConfirmButton(p, tz))


def register(tree: app_commands.CommandTree) -> None:
    @tree.command(name="plan", description="Plan a meeting in plain English")
    @app_commands.describe(request="e.g. '2 hour exec meeting next week before Friday'")
    async def plan(interaction: discord.Interaction, request: str) -> None:
        await interaction.response.defer(thinking=True)

        org = await with_session(service.get_org)
        tz = ZoneInfo(org.timezone) if org and org.timezone else _FALLBACK_TZ

        request_id, status = await with_session(service.create_request, request, None)
        if status == "failed":
            await interaction.followup.send(
                embed=embeds.error_embed(
                    "Couldn't parse that", "Try describing the meeting differently."
                )
            )
            return

        proposals = await with_session(service.get_proposals, request_id)
        if not proposals:
            req = await with_session(service.get_request, request_id)
            await interaction.followup.send(
                embed=embeds.warning_embed(
                    "No conflict-free slots",
                    f"Everyone's booked in that window — try widening it.{_window_line(req, tz)}",
                )
            )
            return

        embed = embeds.info_embed(
            "Proposed times", f"Top {min(5, len(proposals))} conflict-free slots — pick one:"
        )
        for p in proposals[:5]:
            conf = p.conflicts if isinstance(p.conflicts, dict) else {}
            reasons = conf.get("reasons", [])
            free = conf.get("free", [])
            note = f" · {', '.join(reasons)}" if reasons else ""
            value = f"{float(p.attendance_pct or 0):.0f}% weighted attendance{note}"
            if free:
                value += f"\n✅ Available: {', '.join(free)}"
            embed.add_field(name=f"#{p.rank} · {_fmt(p.start_utc, tz)}", value=value, inline=False)
        await interaction.followup.send(embed=embed, view=_ProposalView(proposals, tz))
