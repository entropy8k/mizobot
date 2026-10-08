import discord
from discord.ext import commands

class HelpCog(commands.Cog):
    """Custom help command with an embed."""

    def __init__(self, bot):
        self.bot = bot
        bot.remove_command("help")  # Remove the default help command

    @commands.hybrid_command(name="help", with_app_command=True)
    async def help_command(self, ctx: commands.Context):
        """Shows a custom help embed."""
        embed = discord.Embed(
            title="📜 Command List",
            description="Use `!command` to run a command.\n\nHere’s a list of what I can do:",
            color=discord.Color.blurple()
        )
        embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else discord.Embed.Empty)
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.avatar.url)

        # --- Moderation commands ---
        embed.add_field(
            name="🛠️ Moderation",
            value=(
                "**ban** — Ban a member from the server.\n"
                "**kick** — Kick a member from the server.\n"
                "**mute** — Temporarily mute (timeout) a member.\n"
                "**unban** — Unban a previously banned user.\n"
                "**unmute** — Remove timeout (unmute) from a member.\n"
                "**setstarboard** — Sets the starboard channel.\n"
                "**setrapedboard** — Sets the rapedboard channel.\n"
                "**setrapedemoji** — Sets the rapedboard reaction emote.\n"
                "**nuke** — Deletes every message possible. Use with caution"
            ),
            inline=False
        )

        # --- Music commands ---
        embed.add_field(
            name="🎵 Last.fm",
            value=(
                "**topalbums** — Creates a collage of top albums.\n"
                "**setuser** — Sets your last.fm username.\n"
                "**leaderboard** — Shows a leaderboard for a particular artist.\n"
                "**albumleaderboard** — Shows a leaderboard for a particular album.\n"
                "**artistgenres** — Gets the genres of an artist.\n"
                "**topbands** — Shows your most listened to bands for certain genres.\n"
                "**topgenres** — Shows your most listened to genres.\n"
                "**albumrecs** — Recommends albums based on recent activity.\n"
                "**lastfm** — Shows the current track you are scrobbling."
            ),
            inline=False
        )

        # --- Music commands ---
        embed.add_field(
            name="🎵 Music",
            value=(
                "**join** — Join your voice channel.\n"
                "**leave** — Leave the voice channel.\n"
                "**play** — Play a song or add it to the queue.\n"
                "**queue** — Show the current song queue.\n"
                "**skip** — Skip the current song.\n"
                "**stop** — Stop playback and clear the queue."
            ),
            inline=False
        )

        # --- Warnings commands ---
        embed.add_field(
            name="⚠️ Warnings",
            value=(
                "**warn** — Warn a member.\n"
                "**warnings** — Check a member’s warnings.\n"
                "**clearwarnings** — Clear all warnings for a member."
            ),
            inline=False
        )

        # --- Boorus ---
        embed.add_field(
            name="🖼️ Boorus",
            value=(
                "**soyimg** — Fetches a random image/video from the 'ru.\n"
                "**swaimg** — Fetches a random image/video from the Swabooru.\n"
                "**nuttyimg** — Fetches a random image/video from the Nuttybooru."
            ),
            inline=False
        )

        # --- Warnings commands ---
        embed.add_field(
            name="🔍 Search",
            value=(
                "**img** — Searches for images on DuckDuckGo."
            ),
            inline=False
        )

        # --- Fun commands ---
        embed.add_field(
            name="🎉 Fun",
            value=(
                "**8ball** — Ask the magic 8-ball a question.\n"
                "**roll** — Roll a die (default 6 sides).\n"
                "**coinflip** — Flip a coin.\n"
                "**ifunny** — Makes an iFunny style caption GIF.\n"
                "**say** — Make the bot repeat your message."
            ),
            inline=False
        )

        # --- No Category ---
        embed.add_field(
            name="💬 No Category",
            value="**help** — Shows this message.",
            inline=False
        )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(HelpCog(bot))

