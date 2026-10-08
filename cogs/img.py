# cogs/img.py
import discord
from discord.ext import commands
from ddgs import DDGS

class ImageSearchView(discord.ui.View):
    def __init__(self, ctx: commands.Context, results: list):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.results = results
        self.index = 0
        self.message: discord.Message | None = None

    def get_embed(self) -> discord.Embed:
        item = self.results[self.index]
        title = item.get("title") or "Image result"
        image_url = item.get("image")
        source = item.get("source") or ""
        embed = discord.Embed(
            title=title,
            colour=discord.Colour.blue()
        )
        image_url = item.get("image")  # this should be a direct image URL
        embed.set_image(url=image_url)
        embed.set_footer(
            text=f"Requested by {self.ctx.author}",
            icon_url=self.ctx.author.avatar.url if self.ctx.author.avatar else None
        )
        return embed

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("You can't control this search!", ephemeral=True)
            return
        self.index = (self.index - 1) % len(self.results)
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary)
    async def forward(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("You can't control this search!", ephemeral=True)
            return
        self.index = (self.index + 1) % len(self.results)
        await interaction.response.edit_message(embed=self.get_embed(), view=self)


class ImageSearchCog(commands.Cog):
    """Image search cog using DDGS and Discord UI buttons."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="img",
        description="Search DuckDuckGo images and navigate with buttons"
    )
    async def image_search(self, ctx: commands.Context, *, query: str):
        """Search DuckDuckGo images and navigate with buttons."""
        async with ctx.typing():
            results = []

            try:
                with DDGS() as ddgs:
                    results = ddgs.images(query, max_results=10)  # returns a list directly

                if not results:
                    await ctx.send(f"No image results found for `{query}`")
                    return

                view = ImageSearchView(ctx, results)
                message = await ctx.send(embed=view.get_embed(), view=view)
                view.message = message


            except Exception as e:
                await ctx.send(f"An error occurred: `{e}`")
                raise


# Async setup function for discord.py 2.x
async def setup(bot: commands.Bot):
    await bot.add_cog(ImageSearchCog(bot))
