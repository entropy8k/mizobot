import discord
from discord.ext import commands
import asyncio
import random
import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote

BASE_URL = "https://soybooru.com"

class SoyBooruCog(commands.Cog):
    """Fetch random images or videos from SoyBooru user galleries."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()

    async def get_total_pages(self, tag):
        """Get total number of pages or detect single-post redirects."""
        url_tag = quote(tag)
        url = f"{BASE_URL}/post/list/{url_tag}/1"
        async with self.session.get(url, allow_redirects=False) as resp:
            # Detect redirect (single result)
            if resp.status in (301, 302) and "Location" in resp.headers:
                redirect_url = urljoin(BASE_URL, resp.headers["Location"])
                return "single", redirect_url

            if resp.status != 200:
                return 1, None

            html = await resp.text()
            soup = BeautifulSoup(html, "html.parser")

            # Try to find "Last" page link
            last_link = soup.find("a", string="Last")
            if last_link and last_link.get("href"):
                try:
                    total_pages = int(last_link["href"].rstrip("/").split("/")[-1])
                    return total_pages, None
                except ValueError:
                    pass

            # Fallback: numeric pagination
            pages = [int(a.text) for a in soup.select("div.pages a") if a.text.isdigit()]
            return (max(pages) if pages else 1), None

    async def fetch_user_post_pages(self, tag, page=1):
        """Fetch post URLs from a gallery page."""
        url_tag = quote(tag)
        url = f"{BASE_URL}/post/list/{url_tag}/{page}"
        async with self.session.get(url) as resp:
            if resp.status != 200:
                return []
            html = await resp.text()
            soup = BeautifulSoup(html, "html.parser")
            return [urljoin(BASE_URL, a["href"]) for a in soup.select("a.thumb") if a.get("href")]

    async def fetch_full_media(self, post_url):
        """Extract the full image or video URL from a post page."""
        async with self.session.get(post_url) as resp:
            if resp.status != 200:
                return None, None
            html = await resp.text()
            soup = BeautifulSoup(html, "html.parser")

            # Check for video
            video_link = soup.find("a", href=lambda href: href and href.endswith((".mp4", ".webm", ".mov")))
            if video_link:
                href = video_link["href"]
                encoded_href = '/'.join([quote(part) for part in href.split('/')])
                return urljoin(BASE_URL, encoded_href), "video"

            # Fallback to main image
            img = soup.select_one("img#main_image")
            if img and img.get("src"):
                href = img["src"]
                encoded_href = '/'.join([quote(part) for part in href.split('/')])
                return urljoin(BASE_URL, encoded_href), "image"

            return None, None

    async def fetch_random_user_media(self, tag):
        """Fetch a random image or video for a tag, or the only one if single-post redirect."""
        pages, redirect_url = await self.get_total_pages(tag)

        # Single-image redirect
        if pages == "single" and redirect_url:
            media_url, media_type = await self.fetch_full_media(redirect_url)
            return media_url, media_type, redirect_url

        # Normal multi-page case
        total_pages = pages
        random_page = random.randint(1, total_pages)
        post_pages = await self.fetch_user_post_pages(tag, page=random_page)
        if not post_pages:
            return None
        random_post = random.choice(post_pages)
        media_url, media_type = await self.fetch_full_media(random_post)
        return media_url, media_type, random_post

    @commands.hybrid_command(
        name="soyimg",
        with_app_command=True,
        help="Fetch a random SoyBooru image or video by user tag"
    )
    async def soybooru(self, ctx: commands.Context, *, tag: str):
        """Fetch a random image/video from a SoyBooru user gallery."""
        await ctx.defer()
        result = await self.fetch_random_user_media(tag)
        if not result or not result[0]:
            await ctx.send(f"No media found for `{tag}`.")
            return

        media_url, media_type, post_url = result
        embed = discord.Embed(
            title=f"{media_type.capitalize()} from {tag}",
            url=post_url,
            color=0x1abc9c
        )

        if media_type == "image":
            embed.set_image(url=media_url)
        elif media_type == "video":
            embed.description = f"[Click to view video]({media_url})"
            try:
                embed.set_video(url=media_url)
            except Exception:
                pass

        await ctx.send(embed=embed)

    def cog_unload(self):
        asyncio.create_task(self.session.close())


async def setup(bot: commands.Bot):
    await bot.add_cog(SoyBooruCog(bot))
