import discord
from discord.ext import commands, tasks
import re
import aiohttp

class LinkModerator(commands.Cog):
    """Automatically deletes links from non-member users in specific channels."""

    def __init__(self, bot):
        self.bot = bot
        self.channel_id = 1432415328922636383  # Set the channel to monitor
        self.allowed_role = "Juden"          # Role that bypasses deletion
        self.tlds = set()
        self.update_tlds.start()

        # Simple regex to detect potential domain-like patterns
        self.POTENTIAL_LINK_REGEX = re.compile(
            r"\b([a-z0-9.-]+\.[a-z]{2,})\b", re.IGNORECASE
        )

    @tasks.loop(hours=24)
    async def update_tlds(self):
        """Download TLD list from IANA every 24 hours."""
        url = "https://data.iana.org/TLD/tlds-alpha-by-domain.txt"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    # Skip comments (# lines)
                    self.tlds = set(line.strip().lower() for line in text.splitlines() if line and not line.startswith("#"))
                    print(f"[LinkModerator] Loaded {len(self.tlds)} TLDs.")

    @update_tlds.before_loop
    async def before_update(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bots
        if message.author.bot:
            return
        # Only monitor specified channel
        if message.channel.id != self.channel_id:
            return
        # Skip allowed role
        if discord.utils.get(message.author.roles, name=self.allowed_role):
            return

        # Search for potential links
        matches = self.POTENTIAL_LINK_REGEX.findall(message.content)
        for match in matches:
            # Extract TLD from the domain
            tld = match.split(".")[-1].lower()
            if tld in self.tlds:
                try:
                    await message.delete()
                    await message.author.send(
                        f"⚠️ Your message in #{message.channel.name} contained a link "
                        "and was removed because you don't have the required role."
                    )
                except discord.Forbidden:
                    pass
                break  # Stop after first detected link

async def setup(bot):
    await bot.add_cog(LinkModerator(bot))
