import io
import asyncio
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont, ImageSequence
import aiohttp

# === CONFIG ===
DEFAULT_FONT_PATH = "FuturaCondensedBold.otf"  # change if necessary
BAR_PADDING = 20
BAR_BG_COLOR = (255, 255, 255, 255)
TEXT_COLOR = (0, 0, 0, 255)
MAX_DIMENSION = 1024


class IFunny(commands.Cog):
    """Create iFunny-style reaction GIFs (white bar + black text)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.font_path = DEFAULT_FONT_PATH

    # --- Hybrid Command ---
    @commands.hybrid_command(
        name="ifunny",
        description="Create an iFunny-style GIF (white bar with black text on top)."
    )
    @app_commands.describe(
        text="Text to display in the white top bar"
    )
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def ifunny(self, ctx: commands.Context, *, text: str):
        """Works as both a slash and prefix command."""
        await ctx.defer()

        image_bytes = await self._get_image_bytes(ctx)
        if not image_bytes:
            await ctx.reply("❌ Please attach an image/GIF or include an image/GIF URL.")
            return

        try:
            out_bytes = await asyncio.get_event_loop().run_in_executor(
                None, compose_ifunny_gif, text, image_bytes, self.font_path
            )
        except Exception as e:
            await ctx.reply(f"⚠️ Error while creating GIF: `{e}`")
            return

        out_bytes.seek(0)
        file = discord.File(out_bytes, filename="ifunny.gif")
        await ctx.reply(file=file)

    async def _get_image_bytes(self, ctx: commands.Context) -> Optional[bytes]:
        """Get bytes from attachment or URL in message."""
        if ctx.message and ctx.message.attachments:
            return await ctx.message.attachments[0].read()

        if ctx.message:
            for word in ctx.message.content.split():
                if word.startswith(("http://", "https://")):
                    return await fetch_bytes(word)

        async for msg in ctx.channel.history(limit=5):
            if msg.author == ctx.author and msg.attachments:
                return await msg.attachments[0].read()

        return None


# === Helper functions ===

async def fetch_bytes(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise ValueError(f"HTTP {resp.status}")
            return await resp.read()


def _load_font(font_path: str, target_width: int, text: str, padding: int):
    """Try to find the biggest font size that fits horizontally."""
    try:
        size = int(target_width * 0.12)
        while size > 8:
            try:
                font = ImageFont.truetype(font_path, size)
            except Exception:
                break
            draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
            lines = _wrap_text(draw, text, font, target_width - padding * 2)
            max_w = max(draw.textlength(line, font=font) for line in lines)
            if max_w + padding * 2 <= target_width:
                return font
            size -= 2
    except Exception:
        pass
    return ImageFont.load_default()


def _wrap_text(draw, text, font, max_width):
    """Wrap text into lines that fit within max_width."""
    words = text.split()
    lines = []
    current = []
    for word in words:
        test = " ".join(current + [word])
        if draw.textlength(test, font=font) <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def compose_ifunny_gif(text: str, input_bytes: bytes, font_path: str) -> io.BytesIO:
    """Compose the iFunny-style GIF."""
    in_buf = io.BytesIO(input_bytes)
    with Image.open(in_buf) as im:
        frames = []
        durations = []

        try:
            seq = ImageSequence.Iterator(im)
        except Exception:
            seq = [im]

        orig_w, orig_h = im.size
        scale = 1.0
        if max(orig_w, orig_h) > MAX_DIMENSION:
            scale = MAX_DIMENSION / max(orig_w, orig_h)

        for frame in seq:
            frame = frame.convert("RGBA")
            if scale != 1.0:
                new_size = (int(frame.width * scale), int(frame.height * scale))
                frame = frame.resize(new_size, Image.LANCZOS)
            frames.append(frame.copy())
            durations.append(frame.info.get("duration", 100))

        width = frames[0].width
        font = _load_font(font_path, width, text, BAR_PADDING)

        draw_tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        lines = _wrap_text(draw_tmp, text, font, width - BAR_PADDING * 2)
        line_height = font.getbbox("A")[3] - font.getbbox("A")[1]
        line_spacing = int(line_height * 0.6)

        # Dynamic padding for multi-line
        if len(lines) > 1:
            top_pad = BAR_PADDING + 30   # slightly larger top padding
            bottom_pad = BAR_PADDING # smaller bottom padding
        else:
            top_pad = BAR_PADDING
            bottom_pad = BAR_PADDING

        text_h = len(lines) * line_height + (len(lines) - 1) * line_spacing
        bar_h = text_h + top_pad + bottom_pad

        out_frames = []
        for frame in frames:
            canvas = Image.new("RGBA", (width, bar_h + frame.height), (255, 255, 255, 0))
            draw = ImageDraw.Draw(canvas)
            draw.rectangle([(0, 0), (width, bar_h)], fill=BAR_BG_COLOR)

            # Vertically centered text start Y
            y = (bar_h - text_h) // 2
            for line in lines:
                text_w = draw.textlength(line, font=font)
                text_x = (width - text_w) // 2
                draw.text((text_x, y), line, fill=TEXT_COLOR, font=font)
                y += line_height + line_spacing

            canvas.paste(frame, (0, bar_h), frame)
            out_frames.append(canvas.convert("RGBA"))

        out = io.BytesIO()
        paletted = [f.convert("P", palette=Image.ADAPTIVE) for f in out_frames]
        paletted[0].save(out, format="GIF", save_all=True,
                         append_images=paletted[1:], duration=durations,
                         loop=0, disposal=2)
        out.seek(0)
        return out


async def setup(bot: commands.Bot):
    await bot.add_cog(IFunny(bot))
