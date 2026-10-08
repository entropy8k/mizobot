import discord
from discord.ext import commands

class LogsCog(commands.Cog):
    """Automatically logs bot actions with embeds."""

    def __init__(self, bot):
        self.bot = bot
        self.default_channel_name = "logs"

    async def log(self, guild: discord.Guild, title: str, description: str, color=discord.Color.red()):
        """Send an embed log to the log channel (create if missing)."""
        log_channel = discord.utils.get(guild.text_channels, name=self.default_channel_name)

        # Create channel if missing
        if log_channel is None:
            overwrites = {guild.default_role: discord.PermissionOverwrite(send_messages=False)}
            log_channel = await guild.create_text_channel(self.default_channel_name, overwrites=overwrites)

        embed = discord.Embed(title=title, description=description, color=color)
        embed.set_footer(text="Bot Action Log")
        await log_channel.send(embed=embed)

    # ---------------- EVENTS ----------------
    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await self.log(guild, "Member Banned", f"🔨 **{user}** was banned.")

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        await self.log(guild, "Member Unbanned", f"✅ **{user}** was unbanned.", color=discord.Color.green())

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await self.log(member.guild, "Member Left/Kicked", f"👋 **{member}** left the server or was kicked.", color=discord.Color.orange())

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # Timeout changes (mute/unmute)
        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until:
                await self.log(after.guild, "Member Muted", f"🔇 **{after}** was muted until {after.timed_out_until}.")
            else:
                await self.log(after.guild, "Member Unmuted", f"🔈 **{after}** was unmuted.", color=discord.Color.green())

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.author == self.bot.user:
            return
        await self.log(
            message.guild,
            "Message Deleted",
            f"🗑️ Message from **{message.author}** deleted in {message.channel.mention}:\n{message.content}",
            color=discord.Color.dark_grey()
        )

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        await self.log(
            ctx.guild,
            "Command Used",
            f"✅ Command `{ctx.command}` used by **{ctx.author}** in {ctx.channel.mention}",
            color=discord.Color.blue()
        )

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        await self.log(
            ctx.guild,
            "Command Error",
            f"❌ Error in command `{ctx.command}` by **{ctx.author}**:\n{error}",
            color=discord.Color.red()
        )

async def setup(bot):
    await bot.add_cog(LogsCog(bot))
