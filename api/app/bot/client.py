import asyncio
import contextlib
import logging

import discord
from discord import app_commands

from app.bot.commands import plan as plan_commands
from app.bot.commands import resources as resources_commands
from app.bot.commands import budget as budget_commands
from app.config import settings

logger = logging.getLogger("syncup.bot")

intents = discord.Intents.default()
intents.message_content = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

plan_commands.register(tree)
resources_commands.register(tree)
budget_commands.register(tree)


@bot.event
async def on_ready() -> None:
    # Guild-scoped sync is instant; global sync can take up to an hour, which
    # reads as "the bot is broken" during a 24-hour build. Never sync globally
    # until the demo is over.
    guild = discord.Object(id=int(settings.discord_test_guild_id))
    tree.copy_global_to(guild=guild)
    await tree.sync(guild=guild)
    logger.info("SyncUp online as %s", bot.user)


async def start_bot() -> asyncio.Task:
    return asyncio.create_task(bot.start(settings.discord_bot_token))


async def stop_bot(task: asyncio.Task) -> None:
    await bot.close()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task  # wait for the gateway session to fully close before returning
