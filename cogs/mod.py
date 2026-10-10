"""Moderation: kick / ban / unban / mute / unmute / warn / quarantine, all recorded as numbered cases."""
from datetime import timedelta

import discord
from discord.ext import commands

from utils.style import C, embed, fmt_duration, parse_duration, ts

MAX_TIMEOUT = 28 * 86400
WARN_KICK_AT = 3
WARN_BAN_AT = 5

ACTION_STYLE = {
    "warn": ("⚠️", C.WARN), "kick": ("👢", C.MOD), "ban": ("🔨", C.BAD), "unban": ("✅", C.OK),
    "mute": ("🔇", C.WARN), "unmute": ("🔈", C.OK), "quarantine": ("☣️", C.MOD), "unquarantine": ("💊", C.OK),
}


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ------------------------------------------------------------ helpers
    @property
    def db(self):
        return self.bot.db

    def _check_target(self, ctx, target):
        """Return an error string if ctx.author/bot can't act on target, else None."""
        if target.id == ctx.author.id:
            return "You can't do that to yourself."
        if target.id == self.bot.user.id:
            return "Nice try."
        if isinstance(target, discord.Member):
            if target.id == ctx.guild.owner_id:
                return "You can't moderate the server owner."
            if ctx.author.id != ctx.guild.owner_id and target.top_role >= ctx.author.top_role:
                return "That member's top role is equal to or higher than yours."
            if target.top_role >= ctx.guild.me.top_role:
                return "That member's top role is equal to or higher than mine."
        return None

    async def _finish(self, ctx, action, target, reason, duration=None, extra=None, dm=True):
        emoji, color = ACTION_STYLE[action]
        case_no = self.db.add_case(ctx.guild.id, target.id, ctx.author.id, action, reason, duration)
        e = embed(f"{emoji} {action.title()} · Case #{case_no}", color=color)
        e.set_thumbnail(url=target.display_avatar.url)
        e.add_field(name="User", value=f"{target.mention}\n`{target.id}`")
        e.add_field(name="Moderator", value=ctx.author.mention)
        if duration:
            e.add_field(name="Duration", value=fmt_duration(duration))
        if extra:
            e.add_field(name=extra[0], value=extra[1])
        e.add_field(name="Reason", value=reason, inline=False)
        await ctx.send(embed=e)

        row = self.db.get_guild(ctx.guild.id)
        if row and row["modlog_channel"]:
            ch = ctx.guild.get_channel(row["modlog_channel"])
            if ch and ch.id != ctx.channel.id:
                try:
                    await ch.send(embed=e)
                except discord.HTTPException:
                    pass
        self.db.log_event(ctx.guild.id, f"mod_{action}", target.id, ctx.channel.id, f"case #{case_no} by {ctx.author.id}: {reason}")

        if dm and action in {"warn", "kick", "ban", "mute", "quarantine"}:
            try:
                verb = {"warn": "warned", "kick": "kicked", "ban": "banned", "mute": "muted", "quarantine": "quarantined"}[action]
                d = embed(f"{emoji} You were {verb} in {ctx.guild.name}", f"**Reason:** {reason}", color)
                await target.send(embed=d)
            except (discord.HTTPException, AttributeError):
                pass
        return case_no

    async def _deny(self, ctx, msg):
        await ctx.send(embed=embed("Can't do that", msg, C.BAD), ephemeral=True)

    # --------------------------------------------------------------- kick
    @commands.hybrid_command(name="kick", description="Kick a member.")
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    @commands.guild_only()
    async def kick(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        if err := self._check_target(ctx, member):
            return await self._deny(ctx, err)
        await self._finish(ctx, "kick", member, reason)  # DM first, before they lose shared-server access
        await member.kick(reason=f"{ctx.author}: {reason}")

    # ---------------------------------------------------------------- ban
    @commands.hybrid_command(name="ban", description="Ban a user (works on people who already left, too).")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @commands.guild_only()
    async def ban(self, ctx, user: discord.User, *, reason: str = "No reason provided"):
        member = ctx.guild.get_member(user.id)
        if err := self._check_target(ctx, member or user):
            return await self._deny(ctx, err)
        await self._finish(ctx, "ban", user, reason)
        await ctx.guild.ban(user, reason=f"{ctx.author}: {reason}", delete_message_days=0)

    @commands.hybrid_command(name="unban", description="Unban a user by ID or mention.")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @commands.guild_only()
    async def unban(self, ctx, user: discord.User, *, reason: str = "No reason provided"):
        try:
            await ctx.guild.fetch_ban(user)
        except discord.NotFound:
            return await self._deny(ctx, f"**{user}** isn't banned.")
        await ctx.guild.unban(user, reason=f"{ctx.author}: {reason}")
        for c in self.db.user_cases(ctx.guild.id, user.id, "ban", only_active=True):
            self.db.deactivate_case(ctx.guild.id, c["case_no"])
        await self._finish(ctx, "unban", user, reason, dm=False)

    # --------------------------------------------------------------- mute
    @commands.hybrid_command(name="mute", description="Time a member out. Duration like 10m, 2h, 1d (max 28d).")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    @commands.guild_only()
    async def mute(self, ctx, member: discord.Member, duration: str = "10m", *, reason: str = "No reason provided"):
        if err := self._check_target(ctx, member):
            return await self._deny(ctx, err)
        secs = parse_duration(duration)
        if not secs or secs > MAX_TIMEOUT:
            return await self._deny(ctx, "Duration must look like `30m`, `2h`, `1d` and be at most 28 days.")
        await member.timeout(discord.utils.utcnow() + timedelta(seconds=secs),
                             reason=f"{ctx.author}: {reason}")
        await self._finish(ctx, "mute", member, reason, duration=secs,
                           extra=("Ends", ts(discord.utils.utcnow().timestamp() + secs)))

    @commands.hybrid_command(name="unmute", description="Remove a member's timeout.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    @commands.guild_only()
    async def unmute(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        if not member.is_timed_out():
            return await self._deny(ctx, f"{member.mention} isn't muted.")
        await member.timeout(None, reason=f"{ctx.author}: {reason}")
        for c in self.db.user_cases(ctx.guild.id, member.id, "mute", only_active=True):
            self.db.deactivate_case(ctx.guild.id, c["case_no"])
        await self._finish(ctx, "unmute", member, reason, dm=False)

    # --------------------------------------------------------------- warn
    @commands.hybrid_command(name="warn", description="Warn a member (3 warnings = kick, 5 = ban).")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def warn(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        if err := self._check_target(ctx, member):
            return await self._deny(ctx, err)
        count = len(self.db.user_cases(ctx.guild.id, member.id, "warn", only_active=True)) + 1
        await self._finish(ctx, "warn", member, reason, extra=("Active warnings", str(count)))
        me = ctx.guild.me
        if count >= WARN_BAN_AT and me.guild_permissions.ban_members:
            await member.ban(reason=f"Reached {WARN_BAN_AT} warnings")
            self.db.add_case(ctx.guild.id, member.id, self.bot.user.id, "ban", f"Auto: reached {WARN_BAN_AT} warnings")
            await ctx.send(embed=embed("⛔ Auto-ban", f"{member.mention} hit {WARN_BAN_AT} warnings.", C.BAD))
        elif count == WARN_KICK_AT and me.guild_permissions.kick_members:
            await member.kick(reason=f"Reached {WARN_KICK_AT} warnings")
            self.db.add_case(ctx.guild.id, member.id, self.bot.user.id, "kick", f"Auto: reached {WARN_KICK_AT} warnings")
            await ctx.send(embed=embed("🚫 Auto-kick", f"{member.mention} hit {WARN_KICK_AT} warnings.", C.MOD))

    @commands.hybrid_command(name="warnings", description="List a member's active warnings.")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def warnings(self, ctx, member: discord.Member):
        rows = self.db.user_cases(ctx.guild.id, member.id, "warn", only_active=True)
        if not rows:
            return await ctx.send(embed=embed("Warnings", f"{member.mention} has a clean record ✨", C.OK))
        e = embed(f"⚠️ Warnings — {member}", color=C.WARN)
        e.set_thumbnail(url=member.display_avatar.url)
        for r in rows[:10]:
            e.add_field(name=f"Case #{r['case_no']} · {ts(r['created_at'], 'd')}",
                        value=f"{r['reason']}\n— <@{r['mod_id']}>", inline=False)
        e.description = f"**{len(rows)}** active warning(s)"
        await ctx.send(embed=e)

    @commands.hybrid_command(name="delwarn", description="Remove a single warning by case number.")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def delwarn(self, ctx, case_no: int):
        c = self.db.get_case(ctx.guild.id, case_no)
        if not c or c["action"] != "warn":
            return await self._deny(ctx, "That case doesn't exist or isn't a warning.")
        if not self.db.deactivate_case(ctx.guild.id, case_no):
            return await self._deny(ctx, "That warning was already removed.")
        await ctx.send(embed=embed("Warning removed", f"Case #{case_no} for <@{c['user_id']}> is no longer active.", C.OK))

    @commands.hybrid_command(name="clearwarnings", description="Clear all active warnings for a member.")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def clearwarnings(self, ctx, member: discord.Member):
        n = self.db.clear_warns(ctx.guild.id, member.id)
        await ctx.send(embed=embed("Warnings cleared", f"Cleared **{n}** warning(s) for {member.mention}.", C.OK))

    # --------------------------------------------------------- quarantine
    async def _quarantine_role(self, guild):
        row = self.db.get_guild(guild.id)
        role = guild.get_role(row["quarantine_role"]) if row and row["quarantine_role"] else None
        if role:
            return role
        role = await guild.create_role(name="Quarantined", colour=discord.Colour(0x4B4B4B), reason="mizobot quarantine setup")
        self.db.set_guild_field(guild.id, "quarantine_role", role.id)
        deny = discord.PermissionOverwrite(view_channel=False, send_messages=False, connect=False, add_reactions=False)
        for ch in guild.channels:
            try:
                await ch.set_permissions(role, overwrite=deny, reason="mizobot quarantine setup")
            except discord.HTTPException:
                pass
        return role

    @commands.Cog.listener()
    async def on_guild_channel_create(self, ch):
        row = self.db.get_guild(ch.guild.id)
        role = ch.guild.get_role(row["quarantine_role"]) if row and row["quarantine_role"] else None
        if role:
            try:
                await ch.set_permissions(role, view_channel=False, send_messages=False, connect=False)
            except discord.HTTPException:
                pass

    @commands.hybrid_command(name="quarantine", description="Strip a member's roles and lock them out of every channel.")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    @commands.guild_only()
    async def quarantine(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        if err := self._check_target(ctx, member):
            return await self._deny(ctx, err)
        if self.db.is_quarantined(ctx.guild.id, member.id):
            return await self._deny(ctx, f"{member.mention} is already quarantined.")
        await ctx.defer()
        role = await self._quarantine_role(ctx.guild)
        me_top = ctx.guild.me.top_role
        keep = [r for r in member.roles if r.is_default() or r.managed or r >= me_top]
        stash = [r.id for r in member.roles if r not in keep]
        self.db.save_quarantine(ctx.guild.id, member.id, stash)
        await member.edit(roles=keep + [role], reason=f"Quarantine by {ctx.author}: {reason}")
        await self._finish(ctx, "quarantine", member, reason, extra=("Roles stashed", str(len(stash))))

    @commands.hybrid_command(name="unquarantine", description="Release a member and restore their roles.")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    @commands.guild_only()
    async def unquarantine(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        stash = self.db.pop_quarantine(ctx.guild.id, member.id)
        if stash is None:
            return await self._deny(ctx, f"{member.mention} isn't quarantined.")
        row = self.db.get_guild(ctx.guild.id)
        qrole_id = row["quarantine_role"]
        restore = [r for rid in stash if (r := ctx.guild.get_role(rid)) and r < ctx.guild.me.top_role]
        keep = [r for r in member.roles if r.id != qrole_id]
        await member.edit(roles=list({r.id: r for r in keep + restore}.values()), reason=f"Unquarantine by {ctx.author}: {reason}")
        for c in self.db.user_cases(ctx.guild.id, member.id, "quarantine", only_active=True):
            self.db.deactivate_case(ctx.guild.id, c["case_no"])
        await self._finish(ctx, "unquarantine", member, reason, dm=False, extra=("Roles restored", str(len(restore))))

    # ------------------------------------------------------- case lookups
    @commands.hybrid_command(name="case", description="Look up a moderation case by number.")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def case(self, ctx, case_no: int):
        c = self.db.get_case(ctx.guild.id, case_no)
        if not c:
            return await self._deny(ctx, f"No case #{case_no} here.")
        emoji, color = ACTION_STYLE.get(c["action"], ("📄", C.INFO))
        e = embed(f"{emoji} Case #{c['case_no']} · {c['action'].title()}", color=color)
        e.add_field(name="User", value=f"<@{c['user_id']}>")
        e.add_field(name="Moderator", value=f"<@{c['mod_id']}>")
        e.add_field(name="When", value=ts(c["created_at"], "f"))
        if c["duration"]:
            e.add_field(name="Duration", value=fmt_duration(c["duration"]))
        e.add_field(name="Status", value="active" if c["active"] else "resolved")
        e.add_field(name="Reason", value=c["reason"] or "—", inline=False)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="history", aliases=["cases", "modlogs"], description="Full moderation history for a user.")
    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    async def history(self, ctx, user: discord.User):
        rows = self.db.user_cases(ctx.guild.id, user.id)
        if not rows:
            return await ctx.send(embed=embed("History", f"**{user}** has no cases.", C.OK))
        lines = [f"`#{r['case_no']}` {ACTION_STYLE.get(r['action'], ('📄',))[0]} **{r['action']}** {ts(r['created_at'], 'd')} — {(r['reason'] or '')[:60]}"
                 for r in rows[:15]]
        e = embed(f"Mod history — {user}", "\n".join(lines))
        e.set_thumbnail(url=user.display_avatar.url)
        e.set_footer(text=f"{len(rows)} case(s) total · mizobot ✦")
        await ctx.send(embed=e)

    # -------------------------------------------------------------- purge
    @commands.hybrid_command(name="purge", description="Bulk-delete recent messages (max 500).")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    @commands.guild_only()
    async def purge(self, ctx, amount: int):
        amount = min(max(amount, 1), 500)
        await ctx.defer(ephemeral=True)
        deleted = await ctx.channel.purge(limit=amount + (0 if ctx.interaction else 1))
        self.db.log_event(ctx.guild.id, "mod_purge", ctx.author.id, ctx.channel.id, f"{len(deleted)} messages")
        await ctx.send(embed=embed("Purged", f"Deleted **{len(deleted)}** messages.", C.OK), delete_after=5)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
