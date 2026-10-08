import discord
from discord.ext import commands
import random

class Fun(commands.Cog):
    """Fun commands for entertainment (hybrid commands)"""

    def __init__(self, bot):
        self.bot = bot

    # ---------------- 8BALL ----------------
    @commands.hybrid_command(name="8ball", with_app_command=True)
    async def eight_ball(self, ctx: commands.Context, *, question: str):
        """Ask the magic 8-ball a yes/no question."""
        responses = [
            "It is certain.",
            "Without a doubt.",
            "Yes – definitely.",
            "Most likely.",
            "Ask again later.",
            "Cannot predict now.",
            "Don't count on it.",
            "Very doubtful."
        ]
        answer = random.choice(responses)
        await ctx.send(f"🎱 Question: {question}\nAnswer: {answer}")

    # ---------------- ROLL ----------------
    @commands.hybrid_command(name="roll", with_app_command=True)
    async def roll_dice(self, ctx: commands.Context, sides: int = 6):
        """Roll a die with a specified number of sides (default 6)."""
        if sides <= 1:
            return await ctx.send("❌ The die must have at least 2 sides.")
        result = random.randint(1, sides)
        await ctx.send(f"🎲 You rolled a {result} (1-{sides})")

    # ---------------- COINFLIP ----------------
    @commands.hybrid_command(name="coinflip", with_app_command=True)
    async def coin_flip(self, ctx: commands.Context):
        """Flip a coin."""
        result = random.choice(["Heads", "Tails"])
        await ctx.send(f"🪙 The coin landed on **{result}**!")

    # ---------------- SAY ----------------
    @commands.hybrid_command(name="say", with_app_command=True)
    async def say(self, ctx: commands.Context, *, message: str):
        """Make the bot repeat what you say."""
        await ctx.send(message)

# ---------------- Setup ----------------
async def setup(bot):
    await bot.add_cog(Fun(bot))

