import discord
from discord.ext import commands

from utils.style import C, embed

SECTIONS = [
    ("🛡️ Moderation", [
        ("kick / ban / unban", "Remove or restore a user"),
        ("mute / unmute", "Timeout with durations like `30m`, `2h`, `1d`"),
        ("warn / warnings / delwarn / clearwarnings", "Warnings (3 = kick, 5 = ban)"),
        ("quarantine / unquarantine", "Strip roles & lock out; restored on release"),
        ("case / history", "Look up cases and a user's record"),
        ("purge / nuke", "Bulk delete messages"),
    ]),
    ("⚙️ Server setup", [
        ("prefix", "Show or change the prefix"),
        ("setlogchannel / setmodlog", "Where event logs and mod cases go"),
        ("settings / auditlog", "View config and the logged-event database"),
        ("setstarboard / setrapedboard / setrapedemoji", "Board channels"),
    ]),
    ("💰 Mizodollars (M$)", [
        ("balance / daily / baltop", "Everyone starts with M$10,000"),
        ("give", "Send M$ to a user"),
        ("coinflip `<bet>` `[heads|tails]`", "Double or nothing"),
        ("slots `<bet>` / paytable", "Spin to win"),
    ]),
    ("🎵 Last.fm", [
        ("lastfm / setuser", "Now playing & link your account"),
        ("topalbums / topbands / topgenres", "Your stats"),
        ("leaderboard / albumleaderboard", "Server rankings for an artist or album"),
        ("artistgenres / albumrecs", "Discovery"),
    ]),
    ("🎶 Music", [("join / leave / play / queue / skip / stop", "Voice channel player")]),
    ("🎉 Fun", [
        ("8ball / roll / say / ifunny", "Classic fun"),
        ("soyimg / swaimg / nuttyimg / img", "Image commands"),
    ]),
]


class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="help", description="Show everything I can do.")
    async def help_command(self, ctx):
        p = ctx.clean_prefix
        e = embed("✦ mizobot", f"Prefix: `{p}` · also works as slash commands.\nTry `{p}daily` to grab some **M$**.", C.BRAND)
        if self.bot.user.display_avatar:
            e.set_thumbnail(url=self.bot.user.display_avatar.url)
        for title, items in SECTIONS:
            e.add_field(name=title, value="\n".join(f"**{n}** — {d}" for n, d in items), inline=False)
        e.set_footer(text=f"Requested by {ctx.author} · mizobot ✦", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=e)


async def setup(bot):
    await bot.add_cog(HelpCog(bot))
