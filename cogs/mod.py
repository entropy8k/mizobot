import discord
from discord.ext import commands
from discord import app_commands
from datetime import timedelta

class Moderation(commands.Cog):
    """Moderation commands (prefix + slash)."""

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="kick", with_app_command=True)
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, reason: str = None):
        """Kick a member from the server."""
        await member.kick(reason=reason)
        await ctx.send(f"👢 Kicked **{member}** | Reason: {reason or 'No reason provided.'}")

    @commands.hybrid_command(name="ban", with_app_command=True)
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, reason: str = None):
        """Ban a member from the server."""
        await member.ban(reason=reason)
        await ctx.send(f"🔨 Banned **{member}** | Reason: {reason or 'No reason provided.'}")

    @commands.hybrid_command(name="unban", with_app_command=True)
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, username: str):
        """Unban a previously banned user (use their name#discriminator)."""
        banned_users = await ctx.guild.bans()
        name, discriminator = username.split("#")

        for ban_entry in banned_users:
            user = ban_entry.user
            if (user.name, user.discriminator) == (name, discriminator):
                await ctx.guild.unban(user)
                await ctx.send(f"✅ Unbanned **{user}**")
                return
        await ctx.send("❌ User not found in ban list.")

    @commands.hybrid_command(name="mute", with_app_command=True)
    @commands.has_permissions(moderate_members=True)
    async def mute(self, ctx, member: discord.Member, minutes: int = 10, reason: str = None):
        """Temporarily mute (timeout) a member for a set number of minutes."""
        until = discord.utils.utcnow() + timedelta(minutes=minutes)
        await member.timeout(until, reason=reason)
        await ctx.send(f"🔇 Muted **{member}** for **{minutes} minutes** | Reason: {reason or 'No reason provided.'}")

    @commands.hybrid_command(name="unmute", with_app_command=True)
    @commands.has_permissions(moderate_members=True)
    async def unmute(self, ctx, member: discord.Member):
        """Remove timeout (unmute) from a member."""
        await member.timeout(None)
        await ctx.send(f"🔈 Unmuted **{member}**")

    @commands.hybrid_command(name="nuke", with_app_command=True)
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def nuke(self, ctx):
        """Delete all messages in the current channel."""
        channel = ctx.channel

        if not isinstance(channel, discord.TextChannel):
            return await ctx.send("❌ This command can only be used in text channels.")

        await ctx.send("💥 Nuking all messages... this may take a while.")

        while True:
            deleted = await channel.purge(limit=100)
            if not deleted:
                break

        await ctx.send("✅ All messages deleted.")

    @kick.error
    @ban.error
    @unban.error
    @mute.error
    @unmute.error
    async def mod_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("🚫 You don’t have permission to use that command.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("⚠️ Invalid user or argument.")
        else:
            raise error

async def setup(bot):
    await bot.add_cog(Moderation(bot))
