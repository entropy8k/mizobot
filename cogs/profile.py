"""/profile — wallet, server activity and betting record for any user."""
import discord
from discord.ext import commands

from utils.style import C, CURRENCY, embed, money, ts

GAMES = {"coinflip": "🪙 Coinflip", "slots": "🎰 Slots", "blackjack": "🃏 Blackjack", "mines": "💎 Mines",
         "limbo": "🚀 Limbo", "dice": "🎲 Dice"}


def signed(n: int) -> str:
    return f"{'+' if n >= 0 else '-'}{CURRENCY}{abs(n):,}"


class Profile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild and not message.author.bot:
            self.db.bump_activity(message.guild.id, message.author.id)

    @commands.hybrid_command(name="profile", aliases=["p", "stats"], description="View a user's wallet, activity and betting stats.")
    async def profile(self, ctx, user: discord.User = None):
        user = user or ctx.author
        member = ctx.guild.get_member(user.id) if ctx.guild else None
        u = self.db.get_user(user.id)

        e = embed(f"{user.display_name}'s profile", color=member.color.value if member and member.color.value else C.BRAND)
        e.set_thumbnail(url=user.display_avatar.url)
        e.description = f"{user.mention} · `{user.id}`"

        # wallet
        e.add_field(
            name="💰 Wallet",
            value=(f"{money(u['balance'])}\nRank **#{self.db.wealth_rank(user.id)}** richest\n"
                   f"Won {CURRENCY}{u['won']:,} · Lost {CURRENCY}{u['lost']:,}"),
        )

        # activity
        lines = []
        if ctx.guild:
            a = self.db.get_activity(ctx.guild.id, user.id)
            lines.append(f"**{a['messages']:,}** messages here" if a else "No messages tracked here yet")
            if a:
                lines.append(f"Last seen {ts(a['last_message_at'])}")
        lines.append(f"**{self.db.total_messages(user.id):,}** messages total")
        if member and member.joined_at:
            lines.append(f"Joined {ts(member.joined_at.timestamp(), 'D')}")
        lines.append(f"Account made {ts(user.created_at.timestamp(), 'D')}")
        e.add_field(name="💬 Activity", value="\n".join(lines))

        # bets
        stats = self.db.bet_stats(user.id)
        if not stats:
            e.add_field(name="🎲 Bets", value="No bets yet — try `coinflip` or `slots`.", inline=False)
        else:
            total = sum(s["bets"] for s in stats.values())
            wins = sum(s["wins"] for s in stats.values())
            net = sum(s["net"] for s in stats.values())
            best = max(s["best"] for s in stats.values())
            e.add_field(
                name="🎲 Bets overall",
                value=(f"**{total:,}** bets · **{wins / total:.0%}** win rate\n"
                       f"Net **{signed(net)}** · Best win {CURRENCY}{max(best, 0):,}"),
                inline=False,
            )
            for kind, s in stats.items():
                tie = f" · {s['ties']} push" if s["ties"] else ""
                e.add_field(
                    name=GAMES.get(kind, kind),
                    value=f"{s['bets']:,} played · {s['wins']}W / {s['losses']}L{tie}\nNet {signed(s['net'])}",
                )

        # giving
        sent, received = self.db.give_stats(user.id)
        if sent or received:
            e.add_field(name="💸 Gifts", value=f"Sent {CURRENCY}{sent:,}\nReceived {CURRENCY}{received:,}")

        await ctx.send(embed=e)


async def setup(bot):
    await bot.add_cog(Profile(bot))
