import discord
from discord.ext import commands

from utils.style import C, embed


class Settings(commands.Cog):
    """Per-server configuration."""

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="prefix", description="Show or change this server's command prefix.")
    @commands.guild_only()
    async def prefix(self, ctx, new_prefix: str = None):
        current = self.bot.prefixes.get(ctx.guild.id, "!")
        if new_prefix is None:
            return await ctx.send(embed=embed("Prefix", f"My prefix here is `{current}` (or just @mention me)."))
        if not ctx.author.guild_permissions.manage_guild:
            return await ctx.send(embed=embed("No permission", "You need **Manage Server** to change the prefix.", C.BAD))
        if len(new_prefix) > 5 or any(c.isspace() for c in new_prefix):
            return await ctx.send(embed=embed("Invalid prefix", "Max 5 characters, no spaces.", C.BAD))
        self.bot.db.set_guild_field(ctx.guild.id, "prefix", new_prefix)
        self.bot.prefixes[ctx.guild.id] = new_prefix
        await ctx.send(embed=embed("Prefix updated", f"`{current}` → `{new_prefix}`", C.OK))

    @commands.hybrid_command(name="setlogchannel", description="Set the channel for server event logs.")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def setlogchannel(self, ctx, channel: discord.TextChannel):
        self.bot.db.set_guild_field(ctx.guild.id, "log_channel", channel.id)
        await ctx.send(embed=embed("Log channel set", f"Event logs will go to {channel.mention}.", C.OK))

    @commands.hybrid_command(name="setmodlog", description="Set the channel for moderation case logs.")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def setmodlog(self, ctx, channel: discord.TextChannel):
        self.bot.db.set_guild_field(ctx.guild.id, "modlog_channel", channel.id)
        await ctx.send(embed=embed("Mod-log channel set", f"Mod cases will go to {channel.mention}.", C.OK))

    @commands.hybrid_command(name="settings", description="Show this server's bot settings.")
    @commands.guild_only()
    async def settings(self, ctx):
        g = self.bot.db.get_guild(ctx.guild.id)
        def ch(i): return f"<#{i}>" if i else "not set"
        e = embed(f"Settings — {ctx.guild.name}")
        e.add_field(name="Prefix", value=f"`{g['prefix']}`")
        e.add_field(name="Event log", value=ch(g["log_channel"]))
        e.add_field(name="Mod log", value=ch(g["modlog_channel"]))
        e.add_field(name="Quarantine role", value=f"<@&{g['quarantine_role']}>" if g["quarantine_role"] else "auto-created on first use")
        await ctx.send(embed=e)


async def setup(bot):
    await bot.add_cog(Settings(bot))
