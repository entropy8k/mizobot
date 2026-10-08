import discord
from discord.ext import commands
import yt_dlp
import asyncio

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.song_queues = {}  # {guild_id: [ (url, title) ] }

    # ---- Helper: extract audio URL and title ----
    def get_source(self, query):
        ydl_opts = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "default_search": "ytsearch",
            "quiet": True,
            "source_address": "0.0.0.0",  # 👈 forces IPv4 instead of IPv6
            "youtube_client": "tv",
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
            if "entries" in info:
                info = info["entries"][0]
            return info["url"], info["title"]

    # ---- Helper: play next song automatically ----
    async def play_next(self, ctx):
        queue = self.song_queues.get(ctx.guild.id)
        vc = ctx.voice_client

        if queue and len(queue) > 0:
            url, title = queue.pop(0)
            # Await the coroutine
            source = await discord.FFmpegOpusAudio.from_probe(
                url,
                before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                options="-vn"
            )

            # after callback can't be async, schedule with run_coroutine_threadsafe
            def after_play(err):
                if err:
                    print(f"Player error: {err}")
                asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop)

            vc.play(source, after=after_play)
            await ctx.send(f"🎶 Now playing: **{title}**")
        else:
            await ctx.send("✅ Queue finished.")



    # ---- Join ----
    @commands.hybrid_command(name="join", with_app_command=True)
    async def join(self, ctx: commands.Context):
        if ctx.author.voice is None:
            return await ctx.send("❌ You are not in a voice channel.")
        channel = ctx.author.voice.channel
        if ctx.voice_client is None:
            await channel.connect()
        else:
            await ctx.voice_client.move_to(channel)
        await ctx.send(f"🎧 Joined **{channel}**")

    # ---- Play ----
    @commands.hybrid_command(name="play", with_app_command=True)
    async def play(self, ctx: commands.Context, *, query: str):
        if ctx.voice_client is None:
            await ctx.invoke(self.join)

        url, title = self.get_source(query)
        guild_id = ctx.guild.id

        if guild_id not in self.song_queues:
            self.song_queues[guild_id] = []

        queue = self.song_queues[guild_id]

        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            queue.append((url, title))
            await ctx.send(f"➕ Added to queue: **{title}**")
        else:
            source = await discord.FFmpegOpusAudio.from_probe(
                url,
                before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                options="-vn"
            )
            ctx.voice_client.play(
                source,
                after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop)
            )
            await ctx.send(f"🎶 Now playing: **{title}**")


    # ---- Skip ----
    @commands.hybrid_command(name="skip", with_app_command=True)
    async def skip(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("⏭️ Skipped the current song.")
        else:
            await ctx.send("❌ Nothing is playing right now.")

    # ---- Queue ----
    @commands.hybrid_command(name="queue", with_app_command=True)
    async def queue(self, ctx: commands.Context):
        queue = self.song_queues.get(ctx.guild.id)
        if not queue or len(queue) == 0:
            return await ctx.send("🎵 The queue is empty.")
        desc = "\n".join([f"{i+1}. {title}" for i, (_, title) in enumerate(queue)])
        await ctx.send(f"📜 **Current Queue:**\n{desc}")

    # ---- Stop ----
    @commands.hybrid_command(name="stop", with_app_command=True)
    async def stop(self, ctx: commands.Context):
        if ctx.voice_client:
            self.song_queues[ctx.guild.id] = []
            ctx.voice_client.stop()
            await ctx.send("⏹️ Stopped playback and cleared the queue.")

    # ---- Leave ----
    @commands.hybrid_command(name="leave", with_app_command=True)
    async def leave(self, ctx: commands.Context):
        if ctx.voice_client:
            self.song_queues.pop(ctx.guild.id, None)
            await ctx.voice_client.disconnect()
            await ctx.send("👋 Disconnected from the voice channel.")
        else:
            await ctx.send("❌ I'm not connected to a voice channel.")

async def setup(bot):
    await bot.add_cog(Music(bot))
