import discord
from discord.ext import commands
import json
import os

class Warnings(commands.Cog):
    """Warnings system with hybrid commands (prefix + slash)."""

    def __init__(self, bot):
        self.bot = bot
        self.file_path = "warnings.json"
        self.warnings = self.load_warnings()

    def load_warnings(self):
        if os.path.exists(self.file_path):
            with open(self.file_path, "r") as f:
                return json.load(f)
        return {}

    def save_warnings(self):
        with open(self.file_path, "w") as f:
            json.dump(self.warnings, f, indent=4)

    # ---------------- WARN ----------------
    @commands.hybrid_command(name="warn", with_app_command=True)
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
        """Warn a member."""
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)

        self.warnings.setdefault(guild_id, {})
        self.warnings[guild_id].setdefault(user_id, [])

        self.warnings[guild_id][user_id].append(reason)
        self.save_warnings()

        warn_count = len(self.warnings[guild_id][user_id])
        await ctx.send(f"⚠️ {member.mention} has been warned.\nReason: `{reason}`\nTotal warnings: `{warn_count}`")

        # Optional automatic punishments
        if warn_count == 3:
            await ctx.send(f"🚫 {member.mention} has been kicked for reaching 3 warnings.")
            await member.kick(reason="Reached 3 warnings")
        elif warn_count == 5:
            await ctx.send(f"⛔ {member.mention} has been banned for reaching 5 warnings.")
            await member.ban(reason="Reached 5 warnings")

    # ---------------- WARNINGS ----------------
    @commands.hybrid_command(name="warnings", with_app_command=True)
    @commands.has_permissions(manage_messages=True)
    async def warnings_cmd(self, ctx: commands.Context, member: discord.Member):
        """Check a member's warnings."""
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)

        if guild_id not in self.warnings or user_id not in self.warnings[guild_id]:
            return await ctx.send(f"{member.mention} has no warnings ✅")

        warning_list = self.warnings[guild_id][user_id]
        embed = discord.Embed(
            title=f"⚠️ Warnings for {member}",
            color=discord.Color.orange()
        )
        for i, reason in enumerate(warning_list, start=1):
            embed.add_field(name=f"Warning {i}", value=reason, inline=False)
        await ctx.send(embed=embed)

    # ---------------- CLEARWARNINGS ----------------
    @commands.hybrid_command(name="clearwarnings", with_app_command=True)
    @commands.has_permissions(administrator=True)
    async def clearwarnings(self, ctx: commands.Context, member: discord.Member):
        """Clear all warnings for a member."""
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)

        if guild_id in self.warnings and user_id in self.warnings[guild_id]:
            del self.warnings[guild_id][user_id]
            self.save_warnings()
            await ctx.send(f"✅ Cleared all warnings for {member.mention}.")
        else:
            await ctx.send(f"{member.mention} has no warnings to clear.")

# ---------------- Setup ----------------
async def setup(bot):
    await bot.add_cog(Warnings(bot))
