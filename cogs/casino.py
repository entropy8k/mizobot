"""Casino: blackjack, mines, limbo and dice. Stakes are taken up front and settled exactly once."""
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from utils import casino as game
from utils.style import C, CURRENCY, embed, money

log = logging.getLogger("mizobot.casino")

OUTCOME_TEXT = {
    "blackjack": ("🎉 **Blackjack!** Pays 3:2.", C.GOLD),
    "win": ("✅ **You win!**", C.OK),
    "push": ("🤝 **Push** — stake returned.", C.WARN),
    "lose": ("💀 **Dealer wins.**", C.BAD),
    "bust": ("💥 **Bust!**", C.BAD),
}


def signed(n):
    return f"{'+' if n >= 0 else '-'}{CURRENCY}{abs(n):,}"


class Casino(commands.Cog):
    """Blackjack, mines, limbo and dice."""

    def __init__(self, bot):
        self.bot = bot
        self.active = set()   # users with an interactive game open (one at a time)

    @property
    def db(self):
        return self.bot.db

    # ------------------------------------------------------------ helpers
    async def _deny(self, ctx, title, msg):
        await ctx.send(embed=embed(title, msg, C.BAD), ephemeral=True)

    async def _take_bet(self, ctx, raw, interactive=False):
        """Validate and withdraw the stake. Returns the bet, or None after replying."""
        uid = ctx.author.id
        if interactive and uid in self.active:
            await self._deny(ctx, "Game in progress", "Finish your current game first.")
            return None
        bet = game.parse_amount(raw, self.db.balance(uid))
        if bet is None or bet < game.MIN_BET:
            await self._deny(ctx, "Invalid bet", f"Minimum bet is {money(game.MIN_BET)}. Use a number like `500`, `2k`, `half` or `all`.")
            return None
        if not self.db.spend(uid, bet):
            await self._deny(ctx, "Not enough M$", f"You have {money(self.db.balance(uid))}.")
            return None
        if interactive:
            self.active.add(uid)
        return bet

    def settle(self, ctx, kind, staked, payout):
        """Pay out and record the result. Call exactly once per game. Returns net profit."""
        uid = ctx.author.id
        if payout:
            self.db.add(uid, payout)
        net = payout - staked
        if net:
            self.db.record_result(uid, net)
        self.db.add_transaction(getattr(ctx.guild, "id", None), uid, kind, net)
        return net

    # ----------------------------------------------------------- blackjack
    @commands.hybrid_command(name="blackjack", aliases=["bj"], description="Play blackjack with Hit, Stand and Double Down.")
    async def blackjack(self, ctx, amount: str):
        bet = await self._take_bet(ctx, amount, interactive=True)
        if bet is None:
            return
        try:
            g = game.Blackjack(bet)
            view = BlackjackView(self, ctx, g)
            if g.over:                       # natural blackjack on the deal
                return await view.finish()
            view.message = await ctx.send(embed=view.render(), view=view)
        except Exception:
            log.exception("blackjack failed to start")
            self.active.discard(ctx.author.id)
            self.db.add(ctx.author.id, bet)  # refund
            await self._deny(ctx, "Error", "Couldn't start the game — you were refunded.")

    # --------------------------------------------------------------- mines
    @commands.hybrid_command(name="mines", description="Reveal tiles for a growing multiplier — cash out before you hit a bomb.")
    @app_commands.describe(amount="Your bet (e.g. 500, 2k, half, all)", bombs=f"Number of bombs, 1-{game.MINES_MAX_BOMBS} (more = riskier)")
    async def mines(self, ctx, amount: str, bombs: int = 3):
        if not 1 <= bombs <= game.MINES_MAX_BOMBS:
            return await self._deny(ctx, "Invalid bombs", f"Pick between 1 and {game.MINES_MAX_BOMBS} bombs.")
        bet = await self._take_bet(ctx, amount, interactive=True)
        if bet is None:
            return
        try:
            g = game.Mines(bet, bombs)
            view = MinesView(self, ctx, g)
            view.message = await ctx.send(embed=view.render(), view=view)
        except Exception:
            log.exception("mines failed to start")
            self.active.discard(ctx.author.id)
            self.db.add(ctx.author.id, bet)
            await self._deny(ctx, "Error", "Couldn't start the game — you were refunded.")

    # --------------------------------------------------------------- limbo
    @commands.hybrid_command(name="limbo", description="Set a target multiplier. Win if the roll lands at or above it.")
    @app_commands.describe(amount="Your bet (e.g. 500, 2k, half, all)", target=f"Target multiplier, {game.LIMBO_MIN}-{game.LIMBO_MAX:g}")
    async def limbo(self, ctx, amount: str, target: float):
        if not (game.LIMBO_MIN <= target <= game.LIMBO_MAX):
            return await self._deny(ctx, "Invalid target", f"Target must be between {game.LIMBO_MIN}x and {game.LIMBO_MAX:g}x.")
        target = round(target, 2)
        bet = await self._take_bet(ctx, amount)
        if bet is None:
            return
        result = game.limbo_roll()
        won = result >= target
        payout = bet * round(target * 100) // 100 if won else 0   # integer maths: no float off-by-one
        net = self.settle(ctx, "limbo", bet, payout)
        chance = game.limbo_chance(target)
        e = embed("🚀 Limbo", color=C.OK if net > 0 else C.WARN if won else C.BAD)
        e.description = f"## {result:,.2f}x\nTarget **{target:g}x**" + (" — ✅ **hit!**" if won else " — ❌ **missed**")
        e.add_field(name="Win chance", value=f"{chance:.2%}")
        e.add_field(name="Payout", value=f"{money(payout)} ({signed(net)})")
        e.add_field(name="Balance", value=money(self.db.balance(ctx.author.id)))
        await ctx.send(embed=e)

    # ---------------------------------------------------------------- dice
    @commands.hybrid_command(name="dice", description="Roll 0-99.99: bet that it lands over or under your target.")
    @app_commands.describe(amount="Your bet (e.g. 500, 2k, half, all)", direction="Roll over or under the target", target="Target number")
    @app_commands.choices(direction=[app_commands.Choice(name="over", value="over"), app_commands.Choice(name="under", value="under")])
    async def dice(self, ctx, amount: str, direction: str, target: float):
        direction = {"o": "over", "over": "over", "u": "under", "under": "under"}.get(direction.lower())
        if direction is None:
            return await self._deny(ctx, "Invalid direction", "Choose `over` or `under`.")
        t = round(target * 100)
        if not 0 <= t <= 9999 or not game.dice_valid(direction, t):
            lo, hi = (1.00, 95.00) if direction == "under" else (4.99, 98.99)
            return await self._deny(ctx, "Target out of range",
                                    f"For **{direction}**, pick a target between **{lo:.2f}** and **{hi:.2f}** (win chance 1%–95%).")
        bet = await self._take_bet(ctx, amount)
        if bet is None:
            return
        roll = game.dice_roll()
        won = game.dice_won(direction, t, roll)
        mult = game.dice_multiplier(direction, t)
        payout = int(bet * mult) if won else 0
        net = self.settle(ctx, "dice", bet, payout)
        e = embed("🎲 Dice", color=C.OK if won else C.BAD)
        e.description = f"## {roll / 100:.2f}\nYou bet **{direction} {t / 100:.2f}** — " + ("✅ **win!**" if won else "❌ **loss**")
        e.add_field(name="Win chance", value=f"{game.dice_chance(direction, t):.2%}")
        e.add_field(name="Multiplier", value=f"{mult:.3f}x")
        e.add_field(name="Payout", value=f"{money(payout)} ({signed(net)})")
        e.add_field(name="Balance", value=money(self.db.balance(ctx.author.id)))
        await ctx.send(embed=e)


# ====================================================================== views
class OwnerView(discord.ui.View):
    async def interaction_check(self, interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This isn't your game — start your own.", ephemeral=True)
            return False
        return True


class BlackjackView(OwnerView):
    def __init__(self, cog, ctx, g):
        super().__init__(timeout=60)
        self.cog, self.ctx, self.g = cog, ctx, g
        self.message = None
        self.settled = False
        self._refresh()

    def _refresh(self):
        self.double_btn.disabled = not self.g.can_double() or self.cog.db.balance(self.ctx.author.id) < self.g.bet

    def render(self):
        g = self.g
        if g.over:
            text, color = OUTCOME_TEXT[g.outcome]
        else:
            text, color = "Your move.", C.INFO
        e = embed("🃏 Blackjack", text, color)
        dealer = " ".join(game.fmt_card(c) for c in g.dealer) if g.over else f"{game.fmt_card(g.dealer[0])} 🂠"
        dval = game.hand_value(g.dealer) if g.over else "?"
        e.add_field(name=f"Dealer ({dval})", value=f"`{dealer}`")
        e.add_field(name=f"You ({game.hand_value(g.player)})", value=f"`{' '.join(game.fmt_card(c) for c in g.player)}`")
        e.add_field(name="Bet", value=money(g.total_bet) + (" (doubled)" if g.doubled else ""), inline=False)
        return e

    async def finish(self, interaction=None):
        if self.settled:
            return
        self.settled = True
        self.stop()
        g = self.g
        net = self.cog.settle(self.ctx, "blackjack", g.total_bet, g.payout())
        self.cog.active.discard(self.ctx.author.id)
        e = self.render()
        e.add_field(name="Result", value=f"{signed(net)} · Balance {money(self.cog.db.balance(self.ctx.author.id))}", inline=False)
        if interaction:
            await interaction.response.edit_message(embed=e, view=None)
        elif self.message:
            try:
                await self.message.edit(embed=e, view=None)
            except discord.HTTPException:
                pass
        else:
            await self.ctx.send(embed=e)   # natural blackjack: no message exists yet

    async def on_timeout(self):
        if not self.settled and not self.g.over:
            self.g.stand()                 # walking away = standing
            await self.finish()

    async def _update(self, interaction):
        if self.g.over:
            return await self.finish(interaction)
        self._refresh()
        await interaction.response.edit_message(embed=self.render(), view=self)

    @discord.ui.button(label="Hit", emoji="🃏", style=discord.ButtonStyle.primary)
    async def hit_btn(self, interaction, button):
        self.g.hit()
        await self._update(interaction)

    @discord.ui.button(label="Stand", emoji="✋", style=discord.ButtonStyle.secondary)
    async def stand_btn(self, interaction, button):
        self.g.stand()
        await self._update(interaction)

    @discord.ui.button(label="Double Down", emoji="💰", style=discord.ButtonStyle.success)
    async def double_btn(self, interaction, button):
        if not self.g.can_double():
            return await interaction.response.send_message("You can only double on your first move.", ephemeral=True)
        if not self.cog.db.spend(self.ctx.author.id, self.g.bet):
            return await interaction.response.send_message("You can't afford to double.", ephemeral=True)
        self.g.double()
        await self._update(interaction)


class MinesView(OwnerView):
    COLS = 5

    def __init__(self, cog, ctx, g):
        super().__init__(timeout=120)
        self.cog, self.ctx, self.g = cog, ctx, g
        self.message = None
        self.settled = False
        self.tiles = []
        for i in range(game.MINES_TILES):
            b = discord.ui.Button(label="?", style=discord.ButtonStyle.secondary, row=i // self.COLS)
            b.callback = self._tile_cb(i)
            self.tiles.append(b)
            self.add_item(b)
        self.cash_btn = discord.ui.Button(label="Cash out", emoji="💸", style=discord.ButtonStyle.primary,
                                          row=game.MINES_TILES // self.COLS, disabled=True)
        self.cash_btn.callback = self._cash_cb
        self.add_item(self.cash_btn)

    def render(self, final=None):
        g = self.g
        if final == "bomb":
            e = embed("💣 Mines — BOOM", f"You hit a bomb and lost {money(g.bet)}.", C.BAD)
        elif final in ("cashed", "cleared"):
            title = "💎 Mines — board cleared!" if final == "cleared" else "💸 Mines — cashed out"
            e = embed(title, f"You walked away with {money(g.payout())}.", C.OK)
        else:
            e = embed("💎 Mines", "Pick a tile. Each safe tile raises your multiplier — cash out any time.", C.INFO)
        e.add_field(name="Bet", value=money(g.bet))
        e.add_field(name="Bombs", value=str(g.bombs))
        e.add_field(name="Safe found", value=f"{len(g.revealed)}/{g.safe_total}")
        e.add_field(name="Multiplier", value=f"{g.multiplier:.2f}x")
        if final is None:
            e.add_field(name="Cash out now", value=money(g.cashout_value()))
            e.add_field(name="Next tile", value=f"{g.next_multiplier:.2f}x")
        return e

    def _style_board(self, reveal_all):
        for i, b in enumerate(self.tiles):
            if i in self.g.revealed:
                b.label, b.emoji, b.style = None, "💎", discord.ButtonStyle.success
            elif reveal_all:
                b.label = None
                b.emoji = "💣" if i in self.g.bomb_tiles else "💎"
                b.style = discord.ButtonStyle.danger if i in self.g.bomb_tiles else discord.ButtonStyle.secondary
            b.disabled = b.disabled or reveal_all or i in self.g.revealed
        self.cash_btn.disabled = reveal_all or not self.g.revealed

    async def _end(self, final, interaction=None):
        if self.settled:
            return
        self.settled = True
        self.stop()
        g = self.g
        if final == "refund":
            self.cog.db.add(self.ctx.author.id, g.bet)
        else:
            self.cog.settle(self.ctx, "mines", g.bet, g.payout())
        self.cog.active.discard(self.ctx.author.id)
        self._style_board(reveal_all=True)
        for b in self.children:
            b.disabled = True
        e = self.render(final) if final != "refund" else embed("💎 Mines", f"Game abandoned before any move — {money(g.bet)} refunded.", C.DARK)
        if final != "refund":
            e.add_field(name="Balance", value=money(self.cog.db.balance(self.ctx.author.id)), inline=False)
        if interaction:
            await interaction.response.edit_message(embed=e, view=self)
        elif self.message:
            try:
                await self.message.edit(embed=e, view=self)
            except discord.HTTPException:
                pass

    async def on_timeout(self):
        if self.settled:
            return
        await self._end("cashed" if self.g.revealed else "refund")   # idle = cash out (or refund if nothing was risked)

    def _tile_cb(self, i):
        async def cb(interaction):
            result = self.g.reveal(i)
            if result == "bomb":
                return await self._end("bomb", interaction)
            if result == "cleared":
                return await self._end("cleared", interaction)
            if result == "ignored":
                return await interaction.response.defer()
            self._style_board(reveal_all=False)
            await interaction.response.edit_message(embed=self.render(), view=self)
        return cb

    async def _cash_cb(self, interaction):
        if not self.g.revealed:
            return await interaction.response.defer()
        await self._end("cashed", interaction)


async def setup(bot):
    await bot.add_cog(Casino(bot))
