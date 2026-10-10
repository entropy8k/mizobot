"""/work, /crime and /steal — ways to earn (or lose) M$."""
import random
import time

import discord
from discord.ext import commands

from utils.style import C, CURRENCY, embed, fmt_duration, money

rng = random.SystemRandom()

COOLDOWNS = {"work": 60, "crime": 120, "steal": 300}   # seconds, per user
STEAL_VICTIM_COOLDOWN = 600                            # a victim can't be hit again for 10 min
STEAL_CHANCE = 0.45
STEAL_MIN_BALANCE = 500                                # both thief and victim need at least this
STEAL_TAKE = (0.05, 0.15)                              # % of victim's balance on success
STEAL_FINE = (0.10, 0.20)                              # % of thief's balance paid to victim on failure
STEAL_CAP = 25_000

# ------------------------------------------------------------------ work: safe, steady pay
WORK_JOBS = [
    {"emoji": "🍔", "name": "Flip burgers", "min": 100, "max": 250,
     "text": ["You flipped burgers through the lunch rush.", "You only burned a few patties. Manager is *almost* impressed."]},
    {"emoji": "💻", "name": "Freelance coding", "min": 50, "max": 450,
     "text": ["You shipped a landing page for a client who pays in exposure… and also M$.", "Fixed a bug by adding a semicolon. Billed 4 hours."]},
    {"emoji": "🚚", "name": "Deliver packages", "min": 150, "max": 300,
     "text": ["You delivered 40 packages and only lost one to a dog.", "Rain, traffic, and a locked gate — but you made it."]},
    {"emoji": "🎣", "name": "Go fishing", "min": 80, "max": 400,
     "text": ["You sold your catch at the dock.", "A fish the size of your arm. Dinner and profit."]},
    {"emoji": "🎧", "name": "DJ a party", "min": 120, "max": 350,
     "text": ["The crowd went wild during your set.", "You played one banger on repeat. Nobody noticed."]},
]

# ------------------------------------------------------------- crime: big risk, big reward
# chance = success odds; on failure you lose loss_pct of your balance
CRIMES = [
    {"emoji": "🛒", "name": "Shoplift", "chance": 0.70, "min": 200, "max": 600, "loss": (0.03, 0.08),
     "win": ["You pocketed a few things and strolled out.", "The cashier was on their phone. Easy."],
     "lose": ["Caught on camera. You paid a fine.", "A security guard tackled you by the exit."]},
    {"emoji": "💳", "name": "Card fraud", "chance": 0.50, "min": 800, "max": 2500, "loss": (0.08, 0.18),
     "win": ["The charges went through before anyone noticed.", "A stolen card, a fast-food order… and a cashout."],
     "lose": ["The bank flagged the card. Fees galore.", "The card declined and so did your plan."]},
    {"emoji": "🚗", "name": "Steal a car", "chance": 0.40, "min": 1500, "max": 4000, "loss": (0.10, 0.22),
     "win": ["You chopped it for parts and sold them.", "Fast hands, faster getaway."],
     "lose": ["The alarm went off. You ran, minus some cash.", "It was a police car. Oops."]},
    {"emoji": "🏦", "name": "Rob a bank", "chance": 0.28, "min": 3500, "max": 9000, "loss": (0.15, 0.30),
     "win": ["The vault was open and the getaway driver was on time.", "You walked out with a duffel bag. Legend."],
     "lose": ["The dye pack exploded. You dropped the bag and ran.", "The guard was off-duty police. Bail wasn't cheap."]},
]


def _view_check(ctx):
    async def check(interaction: discord.Interaction):
        if interaction.user.id != ctx.author.id:
            await interaction.response.send_message("That menu isn't yours — run the command yourself.", ephemeral=True)
            return False
        return True
    return check


class ChoiceView(discord.ui.View):
    """One button per option; only the invoker can press; first press wins."""

    def __init__(self, ctx, options, style, on_pick):
        super().__init__(timeout=45)
        self.ctx, self.on_pick, self.done, self.message = ctx, on_pick, False, None
        self.interaction_check = _view_check(ctx)
        for opt in options:
            b = discord.ui.Button(label=opt["name"], emoji=opt["emoji"], style=style)
            b.callback = self._make_cb(opt)
            self.add_item(b)

    def _make_cb(self, opt):
        async def cb(interaction: discord.Interaction):
            if self.done:
                return await interaction.response.defer()
            self.done = True
            self.stop()
            await interaction.response.edit_message(embed=self.on_pick(interaction.user.id, opt), view=None)
        return cb

    async def on_timeout(self):
        if self.message and not self.done:
            try:
                await self.message.edit(embed=embed("Timed out", "You took too long to decide.", C.DARK), view=None)
            except discord.HTTPException:
                pass


class Jobs(commands.Cog):
    """Earn M$: work (safe), crime (risky), steal (from players)."""

    def __init__(self, bot):
        self.bot = bot
        self._last = {}          # (kind, user_id) -> unix time of last use
        self._victim_last = {}   # victim id -> unix time of last successful/failed theft

    @property
    def db(self):
        return self.bot.db

    # ------------------------------------------------------------ cooldowns
    def _remaining(self, kind, user_id):
        return max(0, int(self._last.get((kind, user_id), 0) + COOLDOWNS[kind] - time.time()))

    def _start_cd(self, kind, user_id):
        self._last[(kind, user_id)] = time.time()

    async def _cd_message(self, ctx, kind):
        left = self._remaining(kind, ctx.author.id)
        if left:
            await ctx.send(embed=embed("Easy there", f"You can `{kind}` again in **{fmt_duration(left)}**.", C.WARN), ephemeral=True)
            return True
        return False

    # ----------------------------------------------------------------- work
    def _do_work(self, user_id, job):
        if self._remaining("work", user_id):
            return embed("Easy there", f"Still on cooldown ({fmt_duration(self._remaining('work', user_id))}).", C.WARN)
        self._start_cd("work", user_id)
        pay = rng.randint(job["min"], job["max"])
        self.db.add(user_id, pay)
        self.db.add_transaction(None, user_id, "work", pay)
        e = embed(f"{job['emoji']} {job['name']}", f"{rng.choice(job['text'])}\n\nYou earned {money(pay)}.", C.OK)
        e.add_field(name="Balance", value=money(self.db.balance(user_id)))
        return e

    @commands.hybrid_command(name="work", description="Pick a job and earn some safe M$.")
    async def work(self, ctx):
        if await self._cd_message(ctx, "work"):
            return
        lines = [f"{j['emoji']} **{j['name']}** — {CURRENCY}{j['min']:,}–{j['max']:,}" for j in WORK_JOBS]
        view = ChoiceView(ctx, WORK_JOBS, discord.ButtonStyle.success, self._do_work)
        view.message = await ctx.send(embed=embed("💼 Pick a job", "\n".join(lines) + "\n\nHonest work. No risk.", C.INFO), view=view)

    # ---------------------------------------------------------------- crime
    def _do_crime(self, user_id, crime):
        if self._remaining("crime", user_id):
            return embed("Easy there", f"Lay low for {fmt_duration(self._remaining('crime', user_id))}.", C.WARN)
        self._start_cd("crime", user_id)
        if rng.random() < crime["chance"]:
            gain = rng.randint(crime["min"], crime["max"])
            self.db.add(user_id, gain)
            self.db.add_transaction(None, user_id, "crime", gain)
            e = embed(f"{crime['emoji']} {crime['name']} — success", f"{rng.choice(crime['win'])}\n\nYou got away with {money(gain)}.", C.OK)
        else:
            bal = self.db.balance(user_id)
            loss = int(bal * rng.uniform(*crime["loss"]))
            loss = min(max(loss, 50), bal)
            if loss and self.db.spend(user_id, loss):
                self.db.add_transaction(None, user_id, "crime", -loss)
            else:
                loss = 0
            e = embed(f"{crime['emoji']} {crime['name']} — busted", f"{rng.choice(crime['lose'])}\n\nYou lost {money(loss)}.", C.BAD)
        e.add_field(name="Balance", value=money(self.db.balance(user_id)))
        return e

    @commands.hybrid_command(name="crime", description="Commit a crime: big payouts, but you can lose part of your M$.")
    async def crime(self, ctx):
        if await self._cd_message(ctx, "crime"):
            return
        lines = [f"{c['emoji']} **{c['name']}** — {c['chance']:.0%} success · {CURRENCY}{c['min']:,}–{c['max']:,}"
                 f" · lose {c['loss'][0]:.0%}–{c['loss'][1]:.0%} if caught" for c in CRIMES]
        view = ChoiceView(ctx, CRIMES, discord.ButtonStyle.danger, self._do_crime)
        view.message = await ctx.send(embed=embed("🕶️ Pick a crime", "\n".join(lines), C.MOD), view=view)

    # ---------------------------------------------------------------- steal
    @commands.hybrid_command(name="steal", description="Try to steal M$ from another player. Fail and they take yours.")
    @commands.guild_only()
    async def steal(self, ctx, victim: discord.Member):
        me = ctx.author
        if victim.bot or victim.id == me.id:
            return await ctx.send(embed=embed("Nope", "Pick another real player.", C.BAD), ephemeral=True)
        if await self._cd_message(ctx, "steal"):
            return
        left = int(self._victim_last.get(victim.id, 0) + STEAL_VICTIM_COOLDOWN - time.time())
        if left > 0:
            return await ctx.send(embed=embed("Too hot", f"{victim.mention} was just targeted. Try someone else or wait {fmt_duration(left)}.", C.WARN), ephemeral=True)
        tbal, vbal = self.db.balance(me.id), self.db.balance(victim.id)
        if tbal < STEAL_MIN_BALANCE:
            return await ctx.send(embed=embed("Too broke", f"You need at least {money(STEAL_MIN_BALANCE)} to risk it.", C.BAD), ephemeral=True)
        if vbal < STEAL_MIN_BALANCE:
            return await ctx.send(embed=embed("Not worth it", f"{victim.mention} is too poor to rob.", C.WARN), ephemeral=True)

        self._start_cd("steal", me.id)
        self._victim_last[victim.id] = time.time()
        if rng.random() < STEAL_CHANCE:
            take = min(max(int(vbal * rng.uniform(*STEAL_TAKE)), 1), STEAL_CAP)
            if not self.db.transfer(victim.id, me.id, take):
                return await ctx.send(embed=embed("Too late", "They spent it before you got there.", C.WARN))
            self.db.add_transaction(ctx.guild.id, me.id, "steal", take, victim.id)
            self.db.add_transaction(ctx.guild.id, victim.id, "steal", -take, me.id)
            e = embed("🥷 Heist successful", f"{me.mention} swiped {money(take)} from {victim.mention}!", C.OK)
        else:
            fine = min(max(int(tbal * rng.uniform(*STEAL_FINE)), 1), STEAL_CAP)
            if not self.db.transfer(me.id, victim.id, fine):
                fine = 0
            self.db.add_transaction(ctx.guild.id, me.id, "steal", -fine, victim.id)
            self.db.add_transaction(ctx.guild.id, victim.id, "steal", fine, me.id)
            e = embed("🚨 Caught red-handed", f"{victim.mention} caught {me.mention} and took {money(fine)} as payback!", C.BAD)
        e.add_field(name=f"{me.display_name}", value=money(self.db.balance(me.id)))
        e.add_field(name=f"{victim.display_name}", value=money(self.db.balance(victim.id)))
        await ctx.send(content=victim.mention, embed=e)


async def setup(bot):
    await bot.add_cog(Jobs(bot))
