import discord
from discord.ext import commands
import re
import aiohttp

class Rapedboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.gold_threshold = 2
        self.gold_emoji = "1432680522861117441"
        self.goldboard_channel_name = "rapedboard"
        self.message_cache = {}  # maps original_message_id -> goldboard_msg.id

    def _is_gold_emoji(self, emoji):
        if isinstance(self.gold_emoji, int) or str(self.gold_emoji).isdigit():
            return getattr(emoji, "id", None) == int(self.gold_emoji)
        return str(emoji) == self.gold_emoji

    async def _resolve_tenor_gif(self, url: str) -> str | None:
        """Convert a Tenor link to a direct GIF link."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    html = await resp.text()
                    # Tenor GIF URLs often contain 'media.tenor.com' in <meta property="og:image">
                    match = re.search(r'<meta property="og:image" content="([^"]+)"', html)
                    if match:
                        return match.group(1)
        except:
            pass
        return None

    async def _find_all_media_urls(self, message: discord.Message) -> list[str]:
        """Return all URLs that can be embedded (attachments, direct media, Tenor/Giphy/etc.)."""
        urls = []

        # Attachments first
        for attach in message.attachments:
            if attach.content_type and ("image" in attach.content_type or "video" in attach.content_type):
                urls.append(attach.url)

        # Find all URLs in message
        url_pattern = r"https?://[^\s]+"
        raw_urls = re.findall(url_pattern, message.content)

        for url in raw_urls:
            url_lower = url.lower()
            # Direct media
            if any(url_lower.endswith(ext) for ext in [".gif", ".mp4", ".webm", ".png", ".jpg", ".jpeg"]):
                urls.append(url)
            # Tenor/Giphy/etc.
            elif "tenor.com" in url or "giphy.com" in url:
                resolved = await self._resolve_tenor_gif(url)
                if resolved:
                    urls.append(resolved)
                else:
                    urls.append(url)  # fallback if we can't resolve
            else:
                # fallback: try to embed anything else
                urls.append(url)

        return urls

    async def _post_or_update_goldboard(self, reaction, message, gold_count):
        goldboard_channel = discord.utils.get(message.guild.text_channels, name=self.goldboard_channel_name)
        if not goldboard_channel:
            print(f"[Rapedboard] Channel '{self.goldboard_channel_name}' not found in {message.guild.name}")
            return

        urls = await self._find_all_media_urls(message)
        emoji_display = (
            f"<:{reaction.emoji.name}:{reaction.emoji.id}>"
            if isinstance(reaction.emoji, discord.PartialEmoji)
            else str(reaction.emoji)
        )

        content = f"{emoji_display} **{gold_count}** — {message.channel.mention}"
        embed = discord.Embed(
            description=message.content or "(no text)",
            color=discord.Color.gold()
        )
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        embed.add_field(name="Jump to Message", value=f"[Click here]({message.jump_url})", inline=False)
        embed.timestamp = message.created_at

        video_formats = (".mp4", ".webm", ".mov")

        # Attach first image if any
        if urls:
            for url in urls:
                lower = url.lower()
                if any(lower.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif"]):
                    embed.set_image(url=url)
                    break

        # Add videos and extra media in embeds below
        extra_embeds = []
        for url in urls:
            lower = url.lower()
            if any(lower.endswith(ext) for ext in video_formats):
                content += f"\n{url}"
            elif any(lower.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif"]):
                # Avoid duplicating the first embed
                if embed.image.url != url:
                    extra = discord.Embed(color=discord.Color.gold())
                    extra.set_image(url=url)
                    extra_embeds.append(extra)

        # Post or update
        if message.id in self.message_cache:
            try:
                gold_msg = await goldboard_channel.fetch_message(self.message_cache[message.id])
                await gold_msg.edit(content=content, embed=embed)
                print(f"[Rapedboard] Updated message {message.id} with {gold_count} reacts")
            except discord.NotFound:
                self.message_cache.pop(message.id, None)
        else:
            if gold_count >= self.gold_threshold:
                sent = await goldboard_channel.send(content, embed=embed)
                self.message_cache[message.id] = sent.id
                print(f"[Rapedboard] Posted message {message.id} with {gold_count} reacts")

        # Send all remaining embeds (additional images)
        for ex in extra_embeds:
            await goldboard_channel.send(embed=ex)


    async def _handle_reaction_event(self, reaction, user):
        if user.bot:
            return
        message = reaction.message
        if not message.guild or not self._is_gold_emoji(reaction.emoji):
            return

        # Count reactions (optional: exclude author)
        gold_count = 0
        for react in message.reactions:
            if self._is_gold_emoji(react.emoji):
                gold_count = react.count

        await self._post_or_update_goldboard(reaction, message, gold_count)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        await self._handle_reaction_event(reaction, user)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction, user):
        await self._handle_reaction_event(reaction, user)

    @commands.hybrid_command(name="setrapedboard", with_app_command=True)
    @commands.has_permissions(manage_channels=True)
    async def set_goldboard_channel(self, ctx, *, name: str):
        self.goldboard_channel_name = name
        await ctx.send(f"✅ Rapedboard channel set to `{name}`")

    @commands.hybrid_command(name="setrapedemoji", with_app_command=True)
    @commands.has_permissions(manage_guild=True)
    async def set_gold_emoji(self, ctx, emoji: str):
        if emoji.startswith("<:") and emoji.endswith(">"):
            try:
                emoji_id = int(emoji.split(":")[2][:-1])
                self.gold_emoji = emoji_id
                await ctx.send(f"✅ Rapedboard emoji set to {emoji}")
            except Exception:
                await ctx.send("❌ Invalid emoji format.")
        else:
            self.gold_emoji = emoji
            await ctx.send(f"✅ Rapedboard emoji set to `{emoji}`")

async def setup(bot):
    await bot.add_cog(Rapedboard(bot))
