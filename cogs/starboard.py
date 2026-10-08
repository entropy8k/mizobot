import discord
from discord.ext import commands
import re
import aiohttp

class Starboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.star_threshold = 3
        self.starboard_channel_name = "starboard"
        self.message_cache = {}  # maps original_message_id -> starboard_message_id

    async def _resolve_tenor_gif(self, url: str) -> str | None:
        """Convert Tenor link to direct GIF if possible."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    html = await resp.text()
                    match = re.search(r'<meta property="og:image" content="([^"]+)"', html)
                    if match:
                        return match.group(1)
        except:
            return None
        return None

    async def _find_media_urls(self, message: discord.Message) -> list[str]:
        """Find all attachments and direct GIF/image/video URLs."""
        urls = []

        # Attachments
        for attach in message.attachments:
            if attach.content_type and ("image" in attach.content_type or "video" in attach.content_type):
                urls.append(attach.url)

        # URLs in content
        url_pattern = r"https?://[^\s]+"
        raw_urls = re.findall(url_pattern, message.content)

        for url in raw_urls:
            if url.lower().endswith((".gif", ".mp4", ".webm", ".png", ".jpg", ".jpeg")):
                urls.append(url)
            elif "tenor.com" in url or "giphy.com" in url:
                resolved = await self._resolve_tenor_gif(url)
                if resolved:
                    urls.append(resolved)
                else:
                    urls.append(url)  # fallback
            else:
                # optionally include other URLs
                urls.append(url)

        return urls

    async def _update_starboard(self, message: discord.Message, star_count: int):
        starboard_channel = discord.utils.get(message.guild.text_channels, name=self.starboard_channel_name)
        if not starboard_channel:
            print(f"[Starboard] Channel '{self.starboard_channel_name}' not found in {message.guild.name}")
            return

        urls = await self._find_media_urls(message)

        embed = discord.Embed(
            description=message.content or "(no text)",
            color=discord.Color.gold()
        )
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        embed.add_field(name="Jump to Message", value=f"[Click here]({message.jump_url})", inline=False)
        embed.timestamp = message.created_at

        # Detect if first media is image or video
        video_formats = (".mp4", ".webm", ".mov")
        if urls:
            first_url = urls[0]
            if first_url.lower().endswith((".png", ".jpg", ".jpeg", ".gif")):
                embed.set_image(url=first_url)

        content = f"⭐ **{star_count}** — {message.channel.mention}"
        # Append video URLs directly into the message content for auto-embed
        for url in urls:
            if url.lower().endswith(video_formats):
                content += f"\n{url}"

        # Update or post new starboard entry
        if message.id in self.message_cache:
            try:
                star_msg = await starboard_channel.fetch_message(self.message_cache[message.id])
                await star_msg.edit(content=content, embed=embed)
                print(f"[Starboard] Updated message {message.id} with {star_count} stars")
            except discord.NotFound:
                self.message_cache.pop(message.id, None)
        else:
            if star_count >= self.star_threshold:
                sent = await starboard_channel.send(content, embed=embed)
                self.message_cache[message.id] = sent.id
                print(f"[Starboard] Posted message {message.id} with {star_count} stars")

        # Extra embeds for remaining media
        if urls and len(urls) > 1:
            for url in urls[1:]:
                if url.lower().endswith(video_formats):
                    await starboard_channel.send(url)  # auto-embeds video
                else:
                    extra_embed = discord.Embed(color=discord.Color.gold())
                    extra_embed.set_image(url=url)
                    await starboard_channel.send(embed=extra_embed)


    async def _handle_reaction_event(self, reaction, user):
        if user.bot or reaction.emoji != "⭐":
            return
        message = reaction.message
        if not message.guild:
            return

        star_count = 0
        for react in message.reactions:
            if react.emoji == "⭐":
                star_count = react.count

        await self._update_starboard(message, star_count)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        await self._handle_reaction_event(reaction, user)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction, user):
        await self._handle_reaction_event(reaction, user)

    @commands.hybrid_command(name="setstarboard", with_app_command=True)
    @commands.has_permissions(manage_channels=True)
    async def set_starboard_channel(self, ctx, *, name: str):
        self.starboard_channel_name = name
        await ctx.send(f"✅ Starboard channel set to `{name}`")

async def setup(bot):
    await bot.add_cog(Starboard(bot))
