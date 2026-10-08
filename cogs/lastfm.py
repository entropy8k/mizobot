import discord
from discord.ext import commands
import aiohttp
import asyncio
import json
import os
from PIL import Image, ImageDraw, ImageFont
import io
from collections import Counter
from cachetools import TTLCache

LASTFM_API_KEY = "99a3cc2e55f45cfde2d84fbe86b8d7cb"
API_URL = "https://ws.audioscrobbler.com/2.0/"
USERDATA_FILE = "lastfm_users.json"

class LastFMCog(commands.Cog):
    """Check what song you're playing on Last.fm and view leaderboards."""

    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self.userdata = self._load_userdata()

        # Caches
        self.artist_cache = TTLCache(maxsize=1000, ttl=600)       # 10 minutes
        self.album_cache = TTLCache(maxsize=1000, ttl=600)        # 10 minutes
        self.leaderboard_cache = TTLCache(maxsize=200, ttl=120)   # 2 minutes

        # Semaphore to avoid hitting Last.fm rate limits
        self.semaphore = asyncio.Semaphore(5)

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())

    def _load_userdata(self):
        if os.path.exists(USERDATA_FILE):
            with open(USERDATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_userdata(self):
        with open(USERDATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self.userdata, f, indent=2)

    async def _fetch_now_playing(self, username: str):
        params = {
            "method": "user.getrecenttracks",
            "user": username,
            "api_key": LASTFM_API_KEY,
            "format": "json",
            "limit": 1,
        }

        async with self.session.get(API_URL, params=params) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()

        try:
            track = data["recenttracks"]["track"][0]
            artist = track["artist"]["#text"]
            song = track["name"]
            album = track["album"]["#text"]
            is_now_playing = "@attr" in track and track["@attr"].get("nowplaying") == "true"
            image = track["image"][-1]["#text"] if track["image"] else None
            return {
                "artist": artist,
                "song": song,
                "album": album,
                "now_playing": is_now_playing,
                "image": image,
            }
        except (KeyError, IndexError):
            return None

    async def _get_artist_playcount(self, username: str, artist: str):
        """Fetch a user’s playcount for a specific artist using top artists, fallback to recent tracks."""
        # 1️⃣ Try top artists first
        params = {
            "method": "user.gettopartists",
            "user": username,
            "api_key": LASTFM_API_KEY,
            "format": "json",
            "limit": 1000,
            "period": "overall"
        }
        async with self.session.get(API_URL, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                artists = data.get("topartists", {}).get("artist", [])
                if isinstance(artists, dict):
                    artists = [artists]
                for a in artists:
                    if a["name"].lower() == artist.lower():
                        return int(a["playcount"])

        # 2️⃣ Fallback: scan recent tracks (last ~1000 tracks)
        playcount = 0
        page = 1
        while True:
            params = {
                "method": "user.getrecenttracks",
                "user": username,
                "api_key": LASTFM_API_KEY,
                "format": "json",
                "limit": 200,
                "page": page
            }
            async with self.session.get(API_URL, params=params) as resp:
                if resp.status != 200:
                    break
                data = await resp.json()
            tracks = data.get("recenttracks", {}).get("track", [])
            if not tracks:
                break
            for t in tracks:
                if t["artist"]["#text"].lower() == artist.lower():
                    playcount += 1
            total_pages = int(data.get("recenttracks", {}).get("@attr", {}).get("totalPages", 1))
            if page >= total_pages or page >= 5:  # limit to ~1000 tracks max
                break
            page += 1

        return playcount

    @commands.hybrid_command(name="lastfm", description="Check what someone is listening to on Last.fm.")
    async def lastfm(self, ctx: commands.Context, user: discord.User = None):
        user = user or ctx.author
        if str(user.id) not in self.userdata:
            await ctx.reply(f"{user.mention} hasn’t linked their Last.fm account yet.", ephemeral=True if ctx.interaction else False)
            return

        username = self.userdata[str(user.id)]
        track_data = await self._fetch_now_playing(username)
        if not track_data:
            await ctx.reply("Could not fetch data or no recent tracks found.", ephemeral=True if ctx.interaction else False)
            return

        title = f"🎵 {user.display_name}'s Now Playing" if track_data["now_playing"] else f"🎶 {user.display_name} recently listened to"
        embed = discord.Embed(
            title=title,
            description=f"**{track_data['song']}** — *{track_data['artist']}*\nAlbum: {track_data['album']}",
            color=discord.Color.red(),
        )
        if track_data["image"]:
            embed.set_thumbnail(url=track_data["image"])
        embed.set_footer(text=f"Last.fm • {username}")

        if ctx.interaction:
            await ctx.interaction.response.send_message(embed=embed)
        else:
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="setuser", description="Link your Last.fm username.")
    async def setuser(self, ctx: commands.Context, username: str):
        self.userdata[str(ctx.author.id)] = username
        self._save_userdata()
        message = f"✅ Linked your Last.fm account: **{username}**"
        if ctx.interaction:
            await ctx.interaction.response.send_message(message, ephemeral=True)
        else:
            await ctx.send(message)

    @commands.hybrid_command(
        name="leaderboard",
        description="Leaderboard for who listened to an artist the most (with caching and parallel requests)."
    )
    async def leaderboard(self, ctx: commands.Context, *, artist: str = None):
        if ctx.interaction:
            await ctx.interaction.response.defer()

        if not self.userdata:
            msg = "No users have linked their Last.fm accounts yet."
            return await (ctx.interaction.response.send_message(msg, ephemeral=True)
                        if ctx.interaction else ctx.send(msg))

        # If no artist specified → auto-detect from now playing
        if not artist:
            user_id = str(ctx.author.id)
            if user_id not in self.userdata:
                msg = f"{ctx.author.mention} hasn’t linked their Last.fm account yet."
                return await (ctx.interaction.response.send_message(msg, ephemeral=True)
                            if ctx.interaction else ctx.send(msg))

            username = self.userdata[user_id]
            track_data = await self._fetch_now_playing(username)
            if not track_data or not track_data["artist"]:
                msg = "Could not determine currently playing track."
                return await (ctx.interaction.response.send_message(msg, ephemeral=True)
                            if ctx.interaction else ctx.send(msg))
            artist = track_data["artist"]

        # Cached leaderboard check
        cache_key = f"artist:{artist.lower()}"
        if cache_key in self.leaderboard_cache:
            embed = self.leaderboard_cache[cache_key]
            return await (ctx.interaction.followup.send(embed=embed)
                        if ctx.interaction else ctx.send(embed=embed))

        # Define safe function with semaphore + caching
        async def get_artist_playcount(username):
            cache_key_user = f"{username}:{artist.lower()}"
            if cache_key_user in self.artist_cache:
                return self.artist_cache[cache_key_user]
            async with self.semaphore:
                count = await self._get_artist_playcount(username, artist)
            self.artist_cache[cache_key_user] = count
            return count

        # Run in parallel
        tasks = [get_artist_playcount(username) for username in self.userdata.values()]
        counts = await asyncio.gather(*tasks)

        # Combine results
        leaderboard = []
        for (user_id, username), count in zip(self.userdata.items(), counts):
            if count > 0:
                member = ctx.guild.get_member(int(user_id))
                name = member.display_name if member else username
                leaderboard.append((name, count))

        if not leaderboard:
            msg = f"No one has listened to **{artist}** yet."
            return await (ctx.interaction.response.send_message(msg, ephemeral=True)
                        if ctx.interaction else ctx.send(msg))

        leaderboard.sort(key=lambda x: x[1], reverse=True)
        description = "\n".join(f"**{i+1}.** {name} — {count} scrobbles"
                                for i, (name, count) in enumerate(leaderboard[:10]))

        embed = discord.Embed(
            title=f"🎵 {artist} Leaderboard",
            description=description,
            color=discord.Color.green()
        )
        embed.set_footer(text="Data from Last.fm")

        self.leaderboard_cache[cache_key] = embed
        await (ctx.interaction.followup.send(embed=embed)
            if ctx.interaction else ctx.send(embed=embed))


    @commands.hybrid_command(
        name="albumleaderboard",
        description="Leaderboard for who listened to a specific album the most (with caching and parallel requests)."
    )
    async def albumleaderboard(self, ctx: commands.Context, *, album_query: str):
        if ctx.interaction:
            await ctx.interaction.response.defer()

        if not self.userdata:
            msg = "No users have linked their Last.fm accounts yet."
            return await (ctx.interaction.response.send_message(msg, ephemeral=True)
                        if ctx.interaction else ctx.send(msg))

        # Detect "Artist - Album" pattern
        artist_name = None
        album_name = album_query.strip()
        if " - " in album_query:
            parts = album_query.split(" - ", 1)
            artist_name, album_name = parts[0].strip(), parts[1].strip()

        cover_image = None

        # Auto-detect artist if not provided
        if not artist_name:
            params = {
                "method": "album.search",
                "album": album_name,
                "api_key": LASTFM_API_KEY,
                "format": "json",
                "limit": 3
            }
            async with self.session.get(API_URL, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    matches = data.get("results", {}).get("albummatches", {}).get("album", [])
                    if isinstance(matches, dict):
                        matches = [matches]
                    if matches:
                        best = matches[0]
                        album_name = best.get("name", album_name)
                        artist_name = best.get("artist", "")
                        cover_image = best.get("image", [{}])[-1].get("#text", None)
                    else:
                        return await ctx.send(f"Could not find any album matching **{album_name}**.")
                else:
                    return await ctx.send("Failed to search albums from Last.fm.")

        cache_key = f"album:{artist_name.lower()}:{album_name.lower()}"
        if cache_key in self.leaderboard_cache:
            embed = self.leaderboard_cache[cache_key]
            return await (ctx.interaction.followup.send(embed=embed)
                        if ctx.interaction else ctx.send(embed=embed))

        async def get_album_playcount(username: str):
            cache_key_user = f"{username}:{artist_name.lower()}:{album_name.lower()}"
            if cache_key_user in self.album_cache:
                return self.album_cache[cache_key_user]

            async with self.semaphore:
                params = {
                    "method": "album.getinfo",
                    "artist": artist_name,
                    "album": album_name,
                    "user": username,
                    "api_key": LASTFM_API_KEY,
                    "format": "json"
                }
                async with self.session.get(API_URL, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        playcount = data.get("album", {}).get("userplaycount")
                        if playcount:
                            playcount = int(playcount)
                            self.album_cache[cache_key_user] = playcount
                            return playcount

            # fallback: recent tracks (limit depth)
            total = 0
            for page in range(1, 6):
                async with self.semaphore:
                    params = {
                        "method": "user.getrecenttracks",
                        "user": username,
                        "api_key": LASTFM_API_KEY,
                        "format": "json",
                        "limit": 200,
                        "page": page
                    }
                    async with self.session.get(API_URL, params=params) as resp:
                        if resp.status != 200:
                            break
                        data = await resp.json()
                tracks = data.get("recenttracks", {}).get("track", [])
                if not tracks:
                    break
                for t in tracks:
                    if (t.get("album", {}).get("#text", "").lower() == album_name.lower()
                            and t.get("artist", {}).get("#text", "").lower() == artist_name.lower()):
                        total += 1
                total_pages = int(data.get("recenttracks", {}).get("@attr", {}).get("totalPages", 1))
                if page >= total_pages:
                    break

            self.album_cache[cache_key_user] = total
            return total

        # Run all users concurrently
        tasks = [get_album_playcount(username) for username in self.userdata.values()]
        counts = await asyncio.gather(*tasks)

        leaderboard = []
        for (user_id, username), count in zip(self.userdata.items(), counts):
            if count > 0:
                member = ctx.guild.get_member(int(user_id))
                name = member.display_name if member else username
                leaderboard.append((name, count))

        if not leaderboard:
            msg = f"No one has listened to **{album_name}** by **{artist_name}** yet."
            return await (ctx.interaction.response.send_message(msg, ephemeral=True)
                        if ctx.interaction else ctx.send(msg))

        leaderboard.sort(key=lambda x: x[1], reverse=True)
        desc = "\n".join(f"**{i+1}.** {name} — {count} plays"
                        for i, (name, count) in enumerate(leaderboard[:10]))

        embed = discord.Embed(
            title=f"📀 Album Leaderboard: {album_name}",
            description=desc,
            color=discord.Color.purple()
        )
        embed.add_field(name="Artist", value=artist_name, inline=False)
        if cover_image:
            embed.set_thumbnail(url=cover_image)
        embed.set_footer(text="Data from Last.fm")

        self.leaderboard_cache[cache_key] = embed
        await (ctx.interaction.followup.send(embed=embed)
            if ctx.interaction else ctx.send(embed=embed))



    @commands.hybrid_command(
        name="albumrecs",
        description="Recommend albums based on what you’ve listened to in the past month."
    )
    async def albumrecs(self, ctx: commands.Context, user: discord.User = None):
        if ctx.interaction:
            await ctx.interaction.response.defer()
        user = user or ctx.author

        if str(user.id) not in self.userdata:
            await ctx.send(f"{user.mention} hasn’t linked their Last.fm account.")
            return

        username = self.userdata[str(user.id)]

        # 1️⃣ Fetch recent listening history (multiple pages)
        now = int(discord.utils.utcnow().timestamp())
        from_time = now - 30 * 24 * 3600

        all_tracks = []
        for page in range(1, 6):
            params = {
                "method": "user.getrecenttracks",
                "user": username,
                "api_key": LASTFM_API_KEY,
                "format": "json",
                "limit": 200,
                "page": page,
                "from": from_time
            }
            async with self.session.get(API_URL, params=params) as resp:
                if resp.status != 200:
                    break
                data = await resp.json()
            tracks = data.get("recenttracks", {}).get("track", [])
            if not tracks:
                break
            all_tracks.extend(tracks)
            total_pages = int(data.get("recenttracks", {}).get("@attr", {}).get("totalPages", 1))
            if page >= total_pages:
                break

        if not all_tracks:
            if ctx.interaction:
                await ctx.interaction.followup.send("No listening history found for the past month.")
            else:
                await ctx.send("No listening history found for the past month.")
            return

        # 2️⃣ Count albums & artists
        album_counts, artist_counts = {}, {}
        for t in all_tracks:
            album = t.get("album", {}).get("#text")
            artist = t.get("artist", {}).get("#text")
            if not artist:
                continue
            artist_counts[artist] = artist_counts.get(artist, 0) + 1
            if album:
                key = f"{artist} - {album}"
                album_counts[key] = album_counts.get(key, 0) + 1

        top_albums = sorted(album_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top_artists = sorted(artist_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        recommendations = {}

        # 3️⃣ Try album.getsimilar
        for album_key, _ in top_albums:
            artist_name, album_name = album_key.split(" - ", 1)
            params = {
                "method": "album.getsimilar",
                "artist": artist_name,
                "album": album_name,
                "api_key": LASTFM_API_KEY,
                "format": "json",
                "limit": 10
            }
            async with self.session.get(API_URL, params=params) as resp:
                if resp.status != 200:
                    continue
                data = await resp.json()

            similars = data.get("similaralbums", {}).get("album", [])
            if isinstance(similars, dict):
                similars = [similars]

            for s in similars:
                rec_name = s.get("name")
                rec_artist = s.get("artist", {}).get("name")
                match = float(s.get("match", 0))
                if rec_name and rec_artist:
                    key = f"{rec_artist} - {rec_name}"
                    if key not in album_counts:
                        recommendations[key] = max(recommendations.get(key, 0), match)

        # 4️⃣ If still not enough, use artist.getsimilar + artist.gettopalbums
        if len(recommendations) < 5:
            for artist_name, _ in top_artists:
                params = {
                    "method": "artist.getsimilar",
                    "artist": artist_name,
                    "api_key": LASTFM_API_KEY,
                    "format": "json",
                    "limit": 5
                }
                async with self.session.get(API_URL, params=params) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()

                similars = data.get("similarartists", {}).get("artist", [])
                if isinstance(similars, dict):
                    similars = [similars]

                for s in similars:
                    rec_artist = s.get("name")
                    if not rec_artist:
                        continue
                    top_album_params = {
                        "method": "artist.gettopalbums",
                        "artist": rec_artist,
                        "api_key": LASTFM_API_KEY,
                        "format": "json",
                        "limit": 2
                    }
                    async with self.session.get(API_URL, params=top_album_params) as resp2:
                        if resp2.status != 200:
                            continue
                        data2 = await resp2.json()
                    top_albums_data = data2.get("topalbums", {}).get("album", [])
                    if isinstance(top_albums_data, dict):
                        top_albums_data = [top_albums_data]
                    for alb in top_albums_data:
                        rec_name = alb.get("name")
                        key = f"{rec_artist} - {rec_name}"
                        if rec_name and key not in album_counts:
                            recommendations[key] = recommendations.get(key, 0) + 0.05

        # 5️⃣ Final fallback: recommend from tags
        if len(recommendations) < 5 and top_artists:
            top_artist = top_artists[0][0]
            tag_params = {
                "method": "artist.gettoptags",
                "artist": top_artist,
                "api_key": LASTFM_API_KEY,
                "format": "json"
            }
            async with self.session.get(API_URL, params=tag_params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    tags = [t["name"] for t in data.get("toptags", {}).get("tag", [])[:3]]
                    for tag in tags:
                        tag_params2 = {
                            "method": "tag.gettopalbums",
                            "tag": tag,
                            "api_key": LASTFM_API_KEY,
                            "format": "json",
                            "limit": 5
                        }
                        async with self.session.get(API_URL, params=tag_params2) as resp2:
                            if resp2.status != 200:
                                continue
                            data2 = await resp2.json()
                        albums = data2.get("albums", {}).get("album", [])
                        if isinstance(albums, dict):
                            albums = [albums]
                        for a in albums:
                            rec_name = a.get("name")
                            rec_artist = a.get("artist", {}).get("name")
                            if rec_name and rec_artist:
                                key = f"{rec_artist} - {rec_name}"
                                if key not in album_counts:
                                    recommendations[key] = recommendations.get(key, 0) + 0.02

        # 6️⃣ Sort and format results
        sorted_recs = sorted(recommendations.items(), key=lambda x: x[1], reverse=True)[:10]
        if not sorted_recs:
            await ctx.send("Couldn’t find any good recommendations this month — Last.fm’s data may be limited.")
            return

        rec_text = "\n".join(f"**{i+1}.** {name}" for i, (name, _) in enumerate(sorted_recs))
        embed = discord.Embed(
            title=f"🎶 Album Recommendations for {username}",
            description=rec_text,
            color=discord.Color.purple()
        )
        embed.set_footer(text="Based on your listening habits in the past month (via Last.fm)")
        if ctx.interaction:
            await ctx.interaction.followup.send(embed=embed)
        else:
            await ctx.send(embed=embed)



    @commands.hybrid_command(name="topalbums", description="Create a collage of top albums.")
    async def topalbums(self, ctx: commands.Context, size: str = "3x3", period: str = "7day", user: discord.User = None):
        user = user or ctx.author

        async def safe_respond(content: str = None, file: discord.File = None, ephemeral: bool = False):
            """Send a message using the interaction if possible, otherwise fall back to ctx.send.
            Handles already-acknowledged or expired interactions by using followup or ctx.send."""
            try:
                inter = getattr(ctx, "interaction", None)
                if inter:
                    # if response hasn't been sent yet
                    if not inter.response.is_done():
                        await inter.response.send_message(content=content, file=file, ephemeral=ephemeral)
                    else:
                        await inter.followup.send(content=content, file=file, ephemeral=ephemeral)
                else:
                    await ctx.send(content=content, file=file)
            except discord.NotFound:
                # interaction invalid/expired or unknown -> fall back to normal send
                if file:
                    await ctx.send(content=content, file=file)
                else:
                    await ctx.send(content=content)
            except Exception:
                # re-raise other unexpected errors so the bot logs them
                raise

        if str(user.id) not in self.userdata:
            msg = f"{user.mention} hasn’t linked their Last.fm account yet."
            await safe_respond(content=msg, ephemeral=True)
            return

        username = self.userdata[str(user.id)]

        grid_map = {"3x3": 3, "5x5": 5, "10x10": 10}
        if size not in grid_map:
            await safe_respond(content=f"Invalid size. Choose from {', '.join(grid_map.keys())}.")
            return
        grid = grid_map[size]

        PERIOD_MAP = {
            "7day": "7day",
            "14day": "1month",
            "30day": "1month",
            "90day": "3month",
            "180day": "6month",
            "365day": "12month",
            "overall": "overall"
        }

        period_api = PERIOD_MAP.get(period.lower())
        if not period_api:
            await safe_respond(content=f"Invalid period. Choose from: {', '.join(PERIOD_MAP.keys())}.")
            return

        params = {
            "method": "user.gettopalbums",
            "user": username,
            "api_key": LASTFM_API_KEY,
            "format": "json",
            "limit": grid * grid,
            "period": period_api
        }

        async with self.session.get(API_URL, params=params) as resp:
            if resp.status != 200:
                await safe_respond(content="Failed to fetch top albums.")
                return
            data = await resp.json()

        albums = data.get("topalbums", {}).get("album", [])
        if not albums:
            await safe_respond(content="No albums found for this period.")
            return

        async def fetch_image(url):
            """Fetch an album image and return a PIL Image or None."""
            try:
                async with self.session.get(url) as r:
                    if r.status != 200:
                        return None
                    data = await r.read()
                    return Image.open(io.BytesIO(data)).convert("RGBA")
            except Exception:
                return None

        # Build list of fetch tasks or None where missing
        tasks = []
        for album in albums[:grid * grid]:
            images_list = album.get("image", [])
            if not images_list:
                tasks.append(None)
                continue
            img_url = images_list[-1].get("#text")
            if not img_url or not img_url.startswith("http"):
                tasks.append(None)
                continue
            tasks.append(fetch_image(img_url))

        # Launch the real tasks concurrently (skip None)
        real_tasks = [t for t in tasks if t is not None]
        fetched_images = []
        if real_tasks:
            fetched_images = await asyncio.gather(*real_tasks)

        cover_size = 300
        placeholder = Image.new("RGBA", (cover_size, cover_size), (40, 40, 40, 255))
        images = []
        fetch_idx = 0
        for t in tasks:
            if t is None:
                images.append(placeholder.copy())
            else:
                img = fetched_images[fetch_idx]
                fetch_idx += 1
                images.append(img or placeholder.copy())

        collage_size = (cover_size * grid, cover_size * grid)
        collage = Image.new("RGBA", collage_size, (0, 0, 0, 255))
        draw = ImageDraw.Draw(collage)

        # Fonts - fallback to default if arial isn't available
        font_path = "arial.ttf"
        try:
            font_artist = ImageFont.truetype(font_path, 16)
            font_album = ImageFont.truetype(font_path, 12)
        except Exception:
            font_artist = ImageFont.load_default()
            font_album = ImageFont.load_default()

        for idx, img in enumerate(images):
            img = img.resize((cover_size, cover_size))
            x = (idx % grid) * cover_size
            y = (idx // grid) * cover_size
            collage.paste(img, (x, y))

            album_data = albums[idx]
            artist_name = album_data.get("artist", {}).get("name", "")
            album_name = album_data.get("name", "")
            text_x, text_y = x + 5, y + 5

            draw.text(
                (text_x, text_y),
                artist_name,
                font=font_artist,
                fill=(255, 255, 255, 255),
                stroke_width=2,
                stroke_fill=(0, 0, 0, 255)
            )
            draw.text(
                (text_x, text_y + 18),
                album_name,
                font=font_album,
                fill=(255, 255, 255, 255),
                stroke_width=2,
                stroke_fill=(0, 0, 0, 255)
            )

        buf = io.BytesIO()
        collage.save(buf, format="PNG")
        buf.seek(0)
        file = discord.File(buf, filename="collage.png")

        # Send the resulting collage (safe)
        await safe_respond(content=None, file=file)




    @commands.hybrid_command(
        name="topgenres",
        description="Show your top genres using MusicBrainz (with Last.fm fallback)."
    )
    async def topgenres(self, ctx: commands.Context, user: discord.User = None, limit: int = 1000, period: str = "overall"):
        if ctx.interaction:
            await ctx.interaction.response.defer()
        user = user or ctx.author
        if str(user.id) not in self.userdata:
            msg = f"{user.mention} hasn’t linked their Last.fm account yet."
            if ctx.interaction:
                await ctx.interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx.send(msg)
            return

        username = self.userdata[str(user.id)]

        valid_periods = ["7day","14day","30day","180day","365day","overall"]
        if period not in valid_periods:
            await ctx.send(f"Invalid period. Choose from: {', '.join(valid_periods)}")
            return

        params = {
            "method": "user.gettopartists",
            "user": username,
            "api_key": LASTFM_API_KEY,
            "format": "json",
            "limit": min(limit, 1000),
            "period": period,
        }

        async with self.session.get(API_URL, params=params) as resp:
            if resp.status != 200:
                await ctx.send("Failed to fetch top artists from Last.fm.")
                return
            data = await resp.json()

        artists = data.get("topartists", {}).get("artist", [])
        if not artists:
            await ctx.send("No top artists found.")
            return

        genre_counter = Counter()
        semaphore = asyncio.Semaphore(20)  # allow up to 20 concurrent requests

        async def fetch_genres(artist):
            mbid = artist.get("mbid")
            artist_name = artist.get("name")
            headers = {"User-Agent": "LastFMDiscordBot/1.0"}

            async with semaphore:
                # Try MusicBrainz first
                if mbid:
                    try:
                        async with self.session.get(f"https://musicbrainz.org/ws/2/artist/{mbid}?fmt=json&inc=tags", headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
                            if r.status == 200:
                                data_mb = await r.json()
                                for tag in data_mb.get("tags", []):
                                    name = tag.get("name", "").lower()
                                    if name and len(name) > 1:
                                        genre_counter[name] += tag.get("count", 1)
                                        return
                    except:
                        pass

                # Fallback to Last.fm
                try:
                    async with self.session.get(API_URL, params={
                        "method": "artist.gettoptags",
                        "artist": artist_name,
                        "api_key": LASTFM_API_KEY,
                        "format": "json"
                    }, timeout=aiohttp.ClientTimeout(total=10)) as r:
                        if r.status == 200:
                            data_lfm = await r.json()
                            tags = data_lfm.get("toptags", {}).get("tag", [])
                            if isinstance(tags, dict):
                                tags = [tags]
                            for tag in tags:
                                name = tag.get("name", "").lower()
                                if name and len(name) > 1:
                                    genre_counter[name] += int(tag.get("count", 1))
                except:
                    pass

        await asyncio.gather(*(fetch_genres(a) for a in artists[:limit]))

        if not genre_counter:
            await ctx.send("No genre data found for this user.")
            return

        ignore = {"seen live", "favorites", "under 2000 listeners", "favorite"}
        top_genres = [(g, c) for g, c in genre_counter.most_common(25) if g not in ignore]

        description = "\n".join(
            f"**{i+1}.** {genre.title()} — {count} mentions"
            for i, (genre, count) in enumerate(top_genres[:10])
        )

        embed = discord.Embed(
            title=f"🎧 Top Genres for {user.display_name}",
            description=description or "No valid genre data found.",
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Based on {len(artists[:limit])} top artists (MusicBrainz + Last.fm fallback)")

        if ctx.interaction:
            await ctx.interaction.followup.send(embed=embed)
        else:
            await ctx.send(embed=embed)


    @commands.hybrid_command(
        name="topbands",
        description="Show your top bands/artists, optionally filtered by genre."
    )
    async def topbands(
        self,
        ctx: commands.Context,
        limit: int = 10,
        user: discord.User | None = None,
        period: str = "overall",
        genre: str | None = None,
    ):
        user = user or ctx.author
        if str(user.id) not in self.userdata:
            msg = f"{user.mention} hasn’t linked their Last.fm account yet."
            if ctx.interaction:
                await ctx.interaction.response.send_message(msg, ephemeral=True)
            else:
                await ctx.send(msg)
            return

        username = self.userdata[str(user.id)]

        # Period mapping
        PERIOD_MAP = {
            "7day": "7day",
            "14day": "1month",
            "30day": "1month",
            "90day": "3month",
            "180day": "6month",
            "365day": "12month",
            "overall": "overall",
        }

        period_api = PERIOD_MAP.get(period.lower())
        if not period_api:
            await ctx.send(f"Invalid period. Choose from: {', '.join(PERIOD_MAP.keys())}")
            return

        # Get top artists
        params = {
            "method": "user.gettopartists",
            "user": username,
            "api_key": LASTFM_API_KEY,
            "format": "json",
            "limit": 1000,
            "period": period_api,
        }

        async with self.session.get(API_URL, params=params) as resp:
            if resp.status != 200:
                await ctx.send("Failed to fetch top artists from Last.fm.")
                return
            data = await resp.json()

        artists = data.get("topartists", {}).get("artist", [])
        if not artists:
            await ctx.send("No top artists found.")
            return

        # If no genre specified → return all artists
        if genre is None:
            names = [a.get("name") for a in artists[:limit]]
            description = "\n".join(f"**{i+1}.** {name}" for i, name in enumerate(names))
            embed = discord.Embed(
                title=f"🎸 Top {limit} Bands/Artists for {user.display_name}",
                description=description,
                color=discord.Color.green(),
            )
            if ctx.interaction:
                await ctx.interaction.followup.send(embed=embed)
            else:
                await ctx.send(embed=embed)
            return

        # Genre filtering
        genre = genre.lower()
        semaphore = asyncio.Semaphore(20)
        genre_matches = []

        async def check_artist(a):
            artist_name = a.get("name")
            async with semaphore:
                try:
                    async with self.session.get(
                        API_URL,
                        params={
                            "method": "artist.gettoptags",
                            "artist": artist_name,
                            "api_key": LASTFM_API_KEY,
                            "format": "json",
                        },
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status != 200:
                            return
                        tags_data = await resp.json()
                        tags = tags_data.get("toptags", {}).get("tag", [])
                        if isinstance(tags, dict):
                            tags = [tags]
                        for tag in tags:
                            if tag.get("name", "").lower() == genre:
                                genre_matches.append(artist_name)
                                return
                except:
                    return

        await asyncio.gather(*(check_artist(a) for a in artists))

        if not genre_matches:
            await ctx.send(f"No top bands found for genre '{genre}'.")
            return

        description = "\n".join(f"**{i+1}.** {name}" for i, name in enumerate(genre_matches[:limit]))
        embed = discord.Embed(
            title=f"🎸 Top {limit} Bands/Artists in {genre.title()} for {user.display_name}",
            description=description,
            color=discord.Color.green(),
        )

        if ctx.interaction:
            await ctx.interaction.followup.send(embed=embed)
        else:
            await ctx.send(embed=embed)




    @commands.hybrid_command(
        name="artistgenres",
        description="Show the genres/tags for a specific artist."
    )
    async def artistgenres(self, ctx: commands.Context, *, artist_name: str):
        if ctx.interaction:
            await ctx.interaction.response.defer()
        headers = {
            "User-Agent": "LastFMDiscordBot/1.0 (https://github.com/mish1; vedivinci@protonmail.com)"
        }

        # 1️⃣ Try MusicBrainz first
        mbid = None
        search_url = f"https://musicbrainz.org/ws/2/artist/?query={artist_name}&fmt=json"
        try:
            async with self.session.get(search_url, headers=headers) as r:
                if r.status == 200:
                    data = await r.json()
                    if data.get("artists"):
                        mbid = data["artists"][0].get("id")
        except:
            pass

        genres = Counter()

        if mbid:
            url = f"https://musicbrainz.org/ws/2/artist/{mbid}?fmt=json&inc=tags"
            try:
                async with self.session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        data = await r.json()
                        for tag in data.get("tags", []):
                            tag_name = tag.get("name", "").lower()
                            if tag_name:
                                genres[tag_name] += tag.get("count", 1)
            except:
                pass

        # 2️⃣ Fallback to Last.fm
        if not genres:
            params = {
                "method": "artist.gettoptags",
                "artist": artist_name,
                "api_key": LASTFM_API_KEY,
                "format": "json"
            }
            try:
                async with self.session.get(API_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        tags = data.get("toptags", {}).get("tag", [])
                        if isinstance(tags, dict):
                            tags = [tags]
                        for tag in tags:
                            tag_name = tag.get("name", "").lower()
                            if tag_name:
                                genres[tag_name] += int(tag.get("count", 1))
            except:
                pass

        if not genres:
            await ctx.send(f"No genres found for '{artist_name}'.")
            return

        top_tags = [f"{g} ({c})" for g, c in genres.most_common(15)]
        embed = discord.Embed(
            title=f"🎶 Genres for {artist_name}",
            description="\n".join(top_tags),
            color=discord.Color.blurple()
        )

        if ctx.interaction:
            await ctx.interaction.followup.send(embed=embed)
        else:
            await ctx.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(LastFMCog(bot))
