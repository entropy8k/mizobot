import logging

from discord.ext import commands

from utils.style import C, embed

log = logging.getLogger("mizobot.errors")


class Errors(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if hasattr(ctx.command, "on_error"):
            return
        error = getattr(error, "original", error)
        if isinstance(error, commands.CommandNotFound):
            return
        msg = None
        if isinstance(error, commands.MissingPermissions):
            msg = "You don't have permission to use that."
        elif isinstance(error, commands.BotMissingPermissions):
            msg = "I'm missing permissions: " + ", ".join(f"`{p}`" for p in error.missing_permissions)
        elif isinstance(error, commands.MissingRequiredArgument):
            msg = f"Missing argument `{error.param.name}`. Try `{ctx.clean_prefix}help`."
        elif isinstance(error, (commands.BadArgument, commands.MemberNotFound, commands.UserNotFound)):
            msg = "Couldn't understand one of those arguments."
        elif isinstance(error, commands.CommandOnCooldown):
            msg = f"Slow down — try again in {error.retry_after:.1f}s."
        elif isinstance(error, commands.NoPrivateMessage):
            msg = "That only works in servers."
        elif isinstance(error, commands.CheckFailure):
            msg = "You can't use that here."
        if msg:
            return await ctx.send(embed=embed("Nope", msg, C.BAD), ephemeral=True)
        log.exception("Unhandled error in %s", ctx.command, exc_info=error)
        await ctx.send(embed=embed("Something broke", "That one's on me — it's been logged.", C.BAD), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Errors(bot))
