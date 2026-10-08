import discord
from discord.ext import commands
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont
import io
import textwrap

class Meme(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.impact_path = "Impact.ttf"
        self.default_font = ImageFont.load_default()

    @commands.hybrid_command(
        name="meme",
        description="Create an Impact-style meme caption on an image."
    )
    @app_commands.describe(
        top="Top caption text",
        bottom="Bottom caption text"
    )
    async def meme(
        self,
        ctx: commands.Context,
        top: str = None,
        bottom: str = None
    ):
        """
        Hybrid command version.
        Usage (prefix): !meme top | bottom (and attach image)
        Usage (slash):  /meme top:".." bottom:".." (and attach image)
        """

        # Handle prefix-style "top | bottom"
        if ctx.prefix and top and "|" in top and bottom is None:
            parts = top.split("|", 1)
            top = parts[0].strip()
            bottom = parts[1].strip()

        # Require image
        if not ctx.message.attachments:
            return await ctx.reply("Attach an image to create a meme.", mention_author=False)

        if top is None:
            top = ""
        if bottom is None:
            bottom = ""

        # Download image
        attachment = ctx.message.attachments[0]
        img_bytes = await attachment.read()
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        width, height = img.size

        draw = ImageDraw.Draw(img)

        # Choose font size
        fontsize = int(height / 10)
        try:
            font = ImageFont.truetype(self.impact_path, fontsize)
        except:
            font = self.default_font

        def draw_text(text, y_pos):
            if not text:
                return

            wrapped = textwrap.fill(text.upper(), width=20)

            # Outline + fill
            def outline_text(x, y):
                for ox in [-2, -1, 0, 1, 2]:
                    for oy in [-2, -1, 0, 1, 2]:
                        draw.text((x + ox, y + oy), wrapped, font=font, fill="black")
                draw.text((x, y), wrapped, font=font, fill="white")

            text_width, text_height = draw.multiline_textsize(wrapped, font=font)
            x = (width - text_width) / 2
            y = y_pos

            outline_text(x, y)

        # Draw captions
        draw_text(top, 0)
        draw_text(bottom, height - int(height / 5))

        # Send result
        with io.BytesIO() as buf:
            img.save(buf, format="JPEG")
            buf.seek(0)
            await ctx.reply(file=discord.File(buf, "meme.jpg"), mention_author=False)

async def setup(bot):
    await bot.add_cog(Meme(bot))
