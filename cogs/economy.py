"""MizoDollars (M$) — a currency with no purpose other than fun. Everyone starts with M$10,000."""
import asyncio
import random

import discord
from discord.ext import commands

from utils.db import STARTING_BALANCE
from utils.style import C, CURRENCY, embed, fmt_duration, money

DAILY_AMOUNT = 1_000
DAILY_COOLDOWN = 24 * 3600

# symbol: (weight, payout multiplier for 3-of-a-kind)
SLOT_SYMBOLS = {"🍒": (30, 4), "🍋": (26, 5), "🍇": (20, 8), "🔔": (12, 12), "⭐": (7, 25), "💎": (4, 60), "7️⃣": (1, 200)}
SLOT_NAMES = list(SLOT_SYMBOLS)
SLOT_WEIGHTS = [v[0] for v in SLOT_SYMBOLS.values()]


def spin_reels():
    return random.choices(SLOT_NAMES, weights=SLOT_WEIGHTS, k=3)


def slot_multiplier(reels):
    a, b, c = reels
    if a == b == c:
        return SLOT_SYMBOLS[a][1]
    if a == b or b == c or a == c:
        return 1.0    # any pair: stake back
    if "🍒" in reels:
        return 0.5    # lone cherry: half back
    return 0


class Economy(commands.Cog):
    """Mizodollars: balance, daily, give, baltop, coinflip, slots."""

    def __init__(self, bot):
        self.bot = bot
        self._locks = {}   # one game at a time per user (prevents bet-spam races)

    @property
    def db(self):
        return self.bot.db

    def _lock(self, user_id):
        return self._locks.setdefault(user_id, asyncio.Lock())

    def _parse_bet(self, user_id, raw: str):
        """'500', '1k', '2.5k', 'all', 'half' -> int, or None."""
        raw = raw.lower().replace(",", "").strip()
        bal = self.db.balance(user_id)
        if raw == "all":
            return bal
        if raw == "half":
            return bal // 2
        try:
            mult = 1
            if raw.endswith("k"):
                raw, mult = raw[:-1], 1_000
            elif raw.endswith("m"):
                raw, mult = raw[:-1], 1_000_000
            return int(float(raw) * mult)
        except ValueError:
            return None

    async def _validate_bet(self, ctx, amount_raw):
        bet = self._parse_bet(ctx.author.id, amount_raw)
        if bet is None or bet < 1:
            await ctx.send(embed=embed("Invalid bet", "Use a number like `500`, `2k`, `half` or `all`.", C.BAD), ephemeral=True)
            return None
        if bet > self.db.balance(ctx.author.id):
            await ctx.send(embed=embed("Not enough mizodollars",
                                       f"You have {money(self.db.balance(ctx.author.id))}.", C.BAD), ephemeral=True)
            return None
        return bet

    # ------------------------------------------------------------ balance
    @commands.hybrid_command(name="balance", aliases=["bal", "wallet"], description="Check your (or someone's) mizodollars.")
    async def balance(self, ctx, user: discord.User = None):
        user = user or ctx.author
        u = self.db.get_user(user.id)
        e = embed(f"💰 {user.display_name}'s wallet", color=C.GOLD)
        e.set_thumbnail(url=user.display_avatar.url)
        e.description = f"# {CURRENCY}{u['balance']:,}"
        e.add_field(name="Total won", value=f"{CURRENCY}{u['won']:,}")
        e.add_field(name="Total lost", value=f"{CURRENCY}{u['lost']:,}")
        await ctx.send(embed=e)

    @commands.hybrid_command(name="daily", description=f"Claim {CURRENCY}{DAILY_AMOUNT:,} every 24 hours.")
    async def daily(self, ctx):
        ok, remaining = self.db.claim_daily(ctx.author.id, DAILY_AMOUNT, DAILY_COOLDOWN)
        if not ok:
            return await ctx.send(embed=embed("Already claimed", f"Come back in **{fmt_duration(remaining)}**.", C.WARN))
        self.db.add_transaction(getattr(ctx.guild, "id", None), ctx.author.id, "daily", DAILY_AMOUNT)
        await ctx.send(embed=embed("🎁 Daily claimed", f"+{money(DAILY_AMOUNT)}\nBalance: {money(self.db.balance(ctx.author.id))}", C.OK))

    # --------------------------------------------------------------- give
    @commands.hybrid_command(name="give", aliases=["pay"], description="Give mizodollars to another user.")
    async def give(self, ctx, user: discord.User, amount: str):
        if user.bot or user.id == ctx.author.id:
            return await ctx.send(embed=embed("Nope", "Pick someone else (and not a bot).", C.BAD), ephemeral=True)
        async with self._lock(ctx.author.id):
            amt = await self._validate_bet(ctx, amount)
            if amt is None:
                return
            self.db.transfer(ctx.author.id, user.id, amt)
            self.db.add_transaction(getattr(ctx.guild, "id", None), ctx.author.id, "give", -amt, user.id)
            self.db.add_transaction(getattr(ctx.guild, "id", None), user.id, "give", amt, ctx.author.id)
        e = embed("💸 Transfer complete", f"{ctx.author.mention} → {user.mention}\n{money(amt)}", C.OK)
        e.add_field(name="Your balance", value=money(self.db.balance(ctx.author.id)))
        await ctx.send(embed=e)

    @commands.hybrid_command(name="baltop", aliases=["rich", "moneyboard"], description="Richest users in mizodollars.")
    async def baltop(self, ctx):
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, r in enumerate(self.db.richest(10)):
            u = self.bot.get_user(r["user_id"])
            lines.append(f"{medals[i] if i < 3 else f'`{i + 1}.`'} **{u.display_name if u else r['user_id']}** — {CURRENCY}{r['balance']:,}")
        await ctx.send(embed=embed("🏆 Richest in mizoland", "\n".join(lines) or "Nobody yet.", C.GOLD))

    # ----------------------------------------------------------- coinflip
    @commands.hybrid_command(name="coinflip", aliases=["cf", "flip"], description="Flip a coin. Add a bet and a side to gamble (2x payout).")
    async def coinflip(self, ctx, amount: str = None, side: str = "heads"):
        result = random.choice(["heads", "tails"])
        if amount is None:  # free flip, like the old command
            return await ctx.send(embed=embed("🪙 Coin flip", f"It landed on **{result}**!"))
        side = side.lower()
        side = {"h": "heads", "t": "tails"}.get(side, side)
        if side not in ("heads", "tails"):
            return await ctx.send(embed=embed("Invalid side", "Pick `heads` or `tails`.", C.BAD), ephemeral=True)
        async with self._lock(ctx.author.id):
            bet = await self._validate_bet(ctx, amount)
            if bet is None:
                return
            self.db.spend(ctx.author.id, bet)
            won = result == side
            if won:
                self.db.add(ctx.author.id, bet * 2)
            net = bet if won else -bet
            self.db.record_result(ctx.author.id, net)
            self.db.add_transaction(getattr(ctx.guild, "id", None), ctx.author.id, "coinflip", net)
        e = embed("🪙 Coin flip", color=C.OK if won else C.BAD)
        e.description = (f"You called **{side}** — it landed on **{result}**.\n\n"
                         + (f"🎉 You won {money(bet)}!" if won else f"💀 You lost {money(bet)}."))
        e.add_field(name="Balance", value=money(self.db.balance(ctx.author.id)))
        await ctx.send(embed=e)

    # -------------------------------------------------------------- slots
    @commands.hybrid_command(name="slots", description="Spin the slot machine with mizodollars.")
    async def slots(self, ctx, amount: str):
        async with self._lock(ctx.author.id):
            bet = await self._validate_bet(ctx, amount)
            if bet is None:
                return
            self.db.spend(ctx.author.id, bet)
            reels = spin_reels()
            mult = slot_multiplier(reels)

            def board(r, status):
                return f"## ┃ {r[0]} ┃ {r[1]} ┃ {r[2]} ┃\n{status}"

            msg = await ctx.send(embed=embed("🎰 Slots", board(["❓"] * 3, "*spinning…*"), C.INFO))
            shown = ["❓"] * 3
            for i in range(3):
                await asyncio.sleep(0.8)
                shown[i] = reels[i]
                rest = ["🎲"] * (2 - i)
                await msg.edit(embed=embed("🎰 Slots", board(shown[: i + 1] + rest, "*spinning…*"), C.INFO))

            payout = int(bet * mult)
            if payout:
                self.db.add(ctx.author.id, payout)
            net = payout - bet
            if net != 0:
                self.db.record_result(ctx.author.id, net)
            self.db.add_transaction(getattr(ctx.guild, "id", None), ctx.author.id, "slots", net)

        if mult >= 25:
            status, color = f"💎 **JACKPOT!** ×{mult:g} — you won {money(payout)}", C.GOLD
        elif net > 0:
            status, color = f"🎉 ×{mult:g} — you won {money(net)}!", C.OK
        elif net == 0:
            status, color = "😮‍💨 Pair — stake returned.", C.WARN
        elif payout:
            status, color = f"😬 Lone cherry — you got {money(payout)} back (lost {money(-net)}).", C.WARN
        else:
            status, color = f"💀 No luck — lost {money(bet)}.", C.BAD
        e = embed("🎰 Slots", board(reels, status), color)
        e.add_field(name="Balance", value=money(self.db.balance(ctx.author.id)))
        await msg.edit(embed=e)

    @commands.hybrid_command(name="paytable", description="Show slot machine payouts.")
    async def paytable(self, ctx):
        lines = [f"{s}{s}{s} — ×{m}" for s, (_, m) in SLOT_SYMBOLS.items()]
        lines += ["Any pair — stake back (×1)", "Lone 🍒 — ×0.5"]
        await ctx.send(embed=embed("🎰 Pay table", "\n".join(lines), C.GOLD))


async def setup(bot):
    await bot.add_cog(Economy(bot))
