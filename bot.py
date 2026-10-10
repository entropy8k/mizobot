import asyncio
import logging
import os

import discord
from discord.ext import commands

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from utils.db import Database, DEFAULT_PREFIX

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("mizobot")

COGS = [
    "cogs.settings", "cogs.errors", "cogs.logs", "cogs.mod", "cogs.economy", "cogs.profile", "cogs.help",
    "cogs.fun", "cogs.music", "cogs.link_moderator", "cogs.starboard",
    "cogs.rapedboard", "cogs.img",
]


class MizoBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix=self.get_prefix_for, intents=intents, help_command=None)
        self.db = Database(os.getenv("MIZOBOT_DB", "mizobot.db"))
        self.prefixes = self.db.all_prefixes()

    async def get_prefix_for(self, bot, message):
        prefix = self.prefixes.get(message.guild.id, DEFAULT_PREFIX) if message.guild else DEFAULT_PREFIX
        return commands.when_mentioned_or(prefix)(bot, message)

    async def setup_hook(self):
        for ext in COGS:
            try:
                await self.load_extension(ext)
                log.info("loaded %s", ext)
            except Exception:
                log.exception("failed to load %s", ext)
        await self.tree.sync()

    async def on_ready(self):
        for guild in self.guilds:
            self.db.ensure_guild(guild)
            self.prefixes.setdefault(guild.id, self.db.get_guild(guild.id)["prefix"])
        await self.change_presence(activity=discord.Game(name="🌊 Surf the new wave"))
        log.info("logged in as %s in %d guilds", self.user, len(self.guilds))

    async def on_guild_join(self, guild):
        self.db.ensure_guild(guild)
        self.prefixes[guild.id] = self.db.get_guild(guild.id)["prefix"]


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Set the DISCORD_TOKEN environment variable (see .env.example).")
    async with MizoBot() as bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
