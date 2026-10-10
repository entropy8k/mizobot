"""The M$ store: custom roles, nicknames and (for a fortune) the mod role."""
import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import aiohttp
import discord
from discord.ext import commands

from utils.style import C, CURRENCY, embed, money, parse_color

PRICE_GIVE_ROLE = 100_000
PRICE_NICK = 25_000
PRICE_MY_ROLE = 50_000
PRICE_MOD = 1_000_000
MOD_ROLE_ID = 1515543179515002921

MAX_ICON_BYTES = 256 * 1024          # Discord's role icon limit
ICON_TYPES = {"image/png", "image/jpeg", "image/gif"}


class IconError(Exception):
    pass


async def fetch_icon(url: str) -> bytes:
    """Download a role icon safely: https only, no private/loopback hosts, no redirects, size-capped."""
    u = urlparse(url.strip())
    if u.scheme != "https" or not u.hostname:
        raise IconError("Icon must be a direct `https://` link to a PNG/JPG/GIF.")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(u.hostname, u.port or 443, type=socket.SOCK_STREAM)
    except OSError:
        raise IconError("Couldn't resolve that icon URL.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise IconError("That icon URL isn't allowed.")
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as s, s.get(url.strip(), allow_redirects=False) as r:
            if r.status != 200:
                raise IconError(f"Icon URL returned HTTP {r.status} (redirects aren't followed — use a direct image link).")
            if r.headers.get("Content-Type", "").split(";")[0].strip().lower() not in ICON_TYPES:
                raise IconError("Icon must be a PNG, JPG or GIF.")
            data = await r.content.read(MAX_ICON_BYTES + 1)
    except (aiohttp.ClientError, asyncio.TimeoutError):
        raise IconError("Couldn't download that icon.")
    if len(data) > MAX_ICON_BYTES:
        raise IconError("Icon must be under 256 KB.")
    return data


class ConfirmView(discord.ui.View):
    def __init__(self, author_id):
        super().__init__(timeout=30)
        self.author_id, self.value = author_id, None

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This isn't your purchase.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Buy", emoji="🛒", style=discord.ButtonStyle.success)
    async def buy(self, interaction, button):
        self.value = True
        self.stop()
        await interaction.response.edit_message(view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        self.value = False
        self.stop()
        await interaction.response.edit_message(view=None)


class Store(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    # -------------------------------------------------------------- helpers
    async def _err(self, ctx, msg):
        await ctx.send(embed=embed("Can't do that", msg, C.BAD), ephemeral=True)

    async def _confirm(self, ctx, title, lines, price):
        """Show a Buy/Cancel prompt. Returns the prompt message if confirmed, else None."""
        bal = self.db.balance(ctx.author.id)
        if bal < price:
            await self._err(ctx, f"That costs {money(price)} and you have {money(bal)}.")
            return None
        view = ConfirmView(ctx.author.id)
        e = embed(f"🛒 {title}", "\n".join(lines) + f"\n\n**Cost:** {money(price)}  ·  **You have:** {money(bal)}", C.GOLD)
        msg = await ctx.send(embed=e, view=view)
        await view.wait()
        if not view.value:
            await msg.edit(embed=embed("Purchase cancelled", "You weren't charged.", C.DARK), view=None)
            return None
        return msg

    async def _charge(self, ctx, msg, price):
        if self.db.spend(ctx.author.id, price):
            return True
        await msg.edit(embed=embed("Purchase failed", "You no longer have enough M$.", C.BAD), view=None)
        return False

    async def _refund(self, ctx, msg, price, reason):
        self.db.add(ctx.author.id, price)
        await msg.edit(embed=embed("Purchase failed — refunded", f"{reason}\nYou got your {money(price)} back.", C.BAD), view=None)

    async def _audit(self, ctx, kind, price, description):
        self.db.add_transaction(ctx.guild.id, ctx.author.id, "store", -price)
        logs = self.bot.get_cog("Logs")
        if logs:
            await logs.record(ctx.guild, f"store_{kind}", "🛒 Store purchase", description, C.GOLD, ctx.author)
        else:
            self.db.log_event(ctx.guild.id, f"store_{kind}", ctx.author.id, ctx.channel.id, description)

    def _role_args(self, ctx, name, color, icon):
        """Validate role options. Returns (name, colour_int, icon_url|None) or an error string."""
        name = (name or "").strip()
        if not 1 <= len(name) <= 100:
            return "Role name must be 1–100 characters."
        c = parse_color(color)
        if c is False:
            return "Color must be hex like `#ff66aa` or a name like `red`."
        if icon and not (ctx.guild.premium_tier >= 2 or "ROLE_ICONS" in ctx.guild.features):
            return "This server can't use role icons (needs Boost level 2). Leave the icon blank."
        return name, (c if c is not None else C.BRAND), (icon or None)

    async def _make_role(self, ctx, target, name, colour, icon_bytes):
        """Create (or update the target's existing store role) and assign it. Returns the role."""
        guild = ctx.guild
        existing_id = self.db.get_custom_role(guild.id, target.id)
        role = guild.get_role(existing_id) if existing_id else None
        kwargs = dict(name=name, colour=discord.Colour(colour), reason=f"M$ store purchase by {ctx.author}")
        if icon_bytes:
            kwargs["display_icon"] = icon_bytes
        if role and role < guild.me.top_role:
            await role.edit(**kwargs)
        else:
            role = await guild.create_role(hoist=False, mentionable=False, **kwargs)
            self.db.set_custom_role(guild.id, target.id, role.id)
        if role not in target.roles:
            await target.add_roles(role, reason=kwargs["reason"])
        return role

    async def _buy_role(self, ctx, target, name, color, icon, price, title):
        await ctx.defer()
        parsed = self._role_args(ctx, name, color, icon)
        if isinstance(parsed, str):
            return await self._err(ctx, parsed)
        name, colour, icon_url = parsed
        icon_bytes = None
        if icon_url:
            try:
                icon_bytes = await fetch_icon(icon_url)
            except IconError as e:
                return await self._err(ctx, str(e))
        replaced = self.db.get_custom_role(ctx.guild.id, target.id) is not None
        lines = [f"**For:** {target.mention}", f"**Name:** {name}", f"**Color:** `#{colour:06x}`",
                 f"**Icon:** {'yes' if icon_bytes else 'none'}"]
        if replaced:
            lines.append("*Replaces their current store role.*")
        msg = await self._confirm(ctx, title, lines, price)
        if msg is None or not await self._charge(ctx, msg, price):
            return
        try:
            role = await self._make_role(ctx, target, name, colour, icon_bytes)
        except discord.HTTPException as e:
            return await self._refund(ctx, msg, price, f"Discord refused: {e.text or e}")
        await self._audit(ctx, "role", price, f"Bought role {role.mention} for {target.mention} ({money(price)})")
        e = embed("✅ Role ready", f"{role.mention} is now on {target.mention}.", C.OK)
        e.add_field(name="Balance", value=money(self.db.balance(ctx.author.id)))
        await msg.edit(embed=e, view=None)

    # ------------------------------------------------------------- the shop
    @commands.hybrid_command(name="store", aliases=["shop"], description="See what you can buy with M$.")
    async def store(self, ctx):
        p = ctx.clean_prefix
        e = embed("🛒 M$ Store", f"You have {money(self.db.balance(ctx.author.id))}", C.GOLD)
        e.add_field(name=f"🎨 Custom role for someone — {CURRENCY}{PRICE_GIVE_ROLE:,}",
                    value=f"`{p}giverole @user \"name\" [color] [icon url]`", inline=False)
        e.add_field(name=f"✏️ Change someone's nickname — {CURRENCY}{PRICE_NICK:,}",
                    value=f"`{p}setnick @user <new nickname>`", inline=False)
        e.add_field(name=f"🌈 Custom role for yourself — {CURRENCY}{PRICE_MY_ROLE:,}",
                    value=f"`{p}myrole \"name\" [color] [icon url]`", inline=False)
        e.add_field(name=f"🛡️ Moderator — {CURRENCY}{PRICE_MOD:,}",
                    value=f"`{p}buymod`", inline=False)
        e.add_field(name="Tips", value="Colors: `#ff66aa` or names like `red`. Use quotes around names with spaces. "
                                       "Icons need a direct https link (PNG/JPG/GIF, under 256 KB) and a server at Boost level 2.",
                    inline=False)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="giverole", description=f"Buy a custom role for someone ({CURRENCY}{PRICE_GIVE_ROLE:,}).")
    @commands.guild_only()
    @commands.bot_has_permissions(manage_roles=True)
    async def giverole(self, ctx, member: discord.Member, name: str, color: str = "", icon: str = ""):
        if member.bot:
            return await self._err(ctx, "Bots don't need fancy roles.")
        await self._buy_role(ctx, member, name, color, icon, PRICE_GIVE_ROLE, "Custom role for someone")

    @commands.hybrid_command(name="myrole", description=f"Buy a custom role for yourself ({CURRENCY}{PRICE_MY_ROLE:,}).")
    @commands.guild_only()
    @commands.bot_has_permissions(manage_roles=True)
    async def myrole(self, ctx, name: str, color: str = "", icon: str = ""):
        await self._buy_role(ctx, ctx.author, name, color, icon, PRICE_MY_ROLE, "Your custom role")

    @commands.hybrid_command(name="setnick", description=f"Change someone's nickname ({CURRENCY}{PRICE_NICK:,}).")
    @commands.guild_only()
    @commands.bot_has_permissions(manage_nicknames=True)
    async def setnick(self, ctx, member: discord.Member, *, nickname: str):
        nickname = nickname.strip()
        if not 1 <= len(nickname) <= 32:
            return await self._err(ctx, "Nicknames must be 1–32 characters.")
        if member.id == ctx.guild.owner_id or member.top_role >= ctx.guild.me.top_role:
            return await self._err(ctx, "I can't change that person's nickname (their role is above mine, or they own the server).")
        msg = await self._confirm(ctx, "Change nickname",
                                  [f"**Who:** {member.mention}", f"**Now:** {member.display_name}", f"**New:** {nickname}"], PRICE_NICK)
        if msg is None or not await self._charge(ctx, msg, PRICE_NICK):
            return
        old = member.display_name
        try:
            await member.edit(nick=nickname, reason=f"M$ store purchase by {ctx.author}")
        except discord.HTTPException as e:
            return await self._refund(ctx, msg, PRICE_NICK, f"Discord refused: {e.text or e}")
        await self._audit(ctx, "nick", PRICE_NICK, f"{ctx.author.mention} renamed {member.mention}: `{old}` → `{nickname}`")
        e = embed("✅ Nickname changed", f"{member.mention} is now **{nickname}**.", C.OK)
        e.add_field(name="Balance", value=money(self.db.balance(ctx.author.id)))
        await msg.edit(embed=e, view=None)

    @commands.hybrid_command(name="buymod", description=f"Buy the moderator role ({CURRENCY}{PRICE_MOD:,}).")
    @commands.guild_only()
    @commands.bot_has_permissions(manage_roles=True)
    async def buymod(self, ctx):
        role = ctx.guild.get_role(MOD_ROLE_ID)
        if role is None:
            return await self._err(ctx, "The mod role isn't available in this server.")
        if role in ctx.author.roles:
            return await self._err(ctx, "You're already a mod.")
        if role >= ctx.guild.me.top_role:
            return await self._err(ctx, "I can't assign that role (it's above mine).")
        msg = await self._confirm(ctx, "Become a moderator", [f"You'll get {role.mention}."], PRICE_MOD)
        if msg is None or not await self._charge(ctx, msg, PRICE_MOD):
            return
        try:
            await ctx.author.add_roles(role, reason="Bought with M$")
        except discord.HTTPException as e:
            return await self._refund(ctx, msg, PRICE_MOD, f"Discord refused: {e.text or e}")
        await self._audit(ctx, "mod", PRICE_MOD, f"{ctx.author.mention} bought {role.mention} ({money(PRICE_MOD)})")
        await msg.edit(embed=embed("🛡️ Welcome to the team", f"{ctx.author.mention} is now {role.mention}.", C.OK), view=None)


async def setup(bot):
    await bot.add_cog(Store(bot))
