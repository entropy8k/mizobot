import discord
from discord.ext import commands
import aiohttp
import random
from bs4 import BeautifulSoup
from urllib.parse import urlencode, urljoin

BASE_URL = "https://www.swaggerswithattitude.com"


class SwaggersWithAttitude(commands.Cog):
    """Fetch random videos or images from SwaggersWithAttitude tags."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def get_total_pages(self, tag: str) -> int:
        """Fetch total number of pages for a tag."""
        params = {"page": 1, "tags": tag}
        url = f"{BASE_URL}/posts?{urlencode(params)}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return 1
                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")

                # Detect pagination
                pages = [
                    int(a.text.strip())
                    for a in soup.select("a.page-link")
                    if a.text.strip().isdigit()
                ]
                return max(pages) if pages else 1

    async def fetch_post_links(self, tag: str, page: int = 1):
        """Fetch all post links from a specific tag page."""
        params = {"page": page, "tags": tag}
        url = f"{BASE_URL}/posts?{urlencode(params)}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")

                post_links = [
                    urljoin(BASE_URL, a["href"])
                    for a in soup.select("a[href^='/post/'], a[href^='/posts/']")
                    if a.get("href") and "/random" not in a["href"]
                ]

                return list(set(post_links))

    async def fetch_full_media(self, post_url: str):
        """Fetch the full image or video from a post page."""
        async with aiohttp.ClientSession() as session:
            async with session.get(post_url) as resp:
                if resp.status != 200:
                    return None, None
                html = await resp.text()
                soup = BeautifulSoup(html, "html.parser")

                video_tag = soup.find("video", {"id": "image"})
                if video_tag and video_tag.get("src"):
                    return urljoin(BASE_URL, video_tag["src"]), "video"

                img_tag = soup.find("img", {"id": "image"})
                if img_tag and img_tag.get("src"):
                    return urljoin(BASE_URL, img_tag["src"]), "image"

                return None, None

    async def fetch_random_media(self, tag: str):
        """Fetch a random media URL for a tag."""
        total_pages = await self.get_total_pages(tag)
        random_page = random.randint(1, total_pages)
        post_links = await self.fetch_post_links(tag, page=random_page)
        if not post_links:
            return None
        random_post = random.choice(post_links)
        media_url, media_type = await self.fetch_full_media(random_post)
        return media_url, media_type, random_post

    @commands.hybrid_command(
        name="swaimg",
        description="Fetch a random image or video from swaggerswithattitude.com by tag.",
    )
    async def swag(self, ctx: commands.Context, *, tag: str):
        """Hybrid command version of swag."""
        # Use proper typing indication for prefix-based commands
        if isinstance(ctx, commands.Context):
            async with ctx.typing():
                result = await self.fetch_random_media(tag)
        else:
            result = await self.fetch_random_media(tag)

        if not result or not result[0]:
            msg = "❌ No media found for that tag."
            if hasattr(ctx, "response"):  # Slash command
                await ctx.response.send_message(msg)
            else:  # Prefix command
                await ctx.reply(msg)
            return

        media_url, media_type, post_url = result
        embed = discord.Embed(
            title=f"{media_type.capitalize()} from {tag}",
            url=post_url,
            color=discord.Color.gold(),
        )
        if media_type == "image":
            embed.set_image(url=media_url)
        else:
            embed.description = f"[🎥 Video Link]({media_url})"


        if hasattr(ctx, "response"):  # Slash command
            await ctx.response.send_message(embed=embed)
        else:  # Prefix command
            await ctx.reply(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(SwaggersWithAttitude(bot))
