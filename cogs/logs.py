"""Event logging: every event goes to the database; if a log channel is set it's also posted as an embed."""
import discord
from discord.ext import commands

from utils.style import C, embed, ts


class Logs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def record(self, guild, type_, title, description, color=C.INFO, user=None, channel=None):
        """Persist an event and post it to the log channel (if configured)."""
        if guild is None:
            return
        self.bot.db.log_event(guild.id, type_, getattr(user, "id", None), getattr(channel, "id", None), description)
        row = self.bot.db.get_guild(guild.id)
        if not row or not row["log_channel"]:
            return
        ch = guild.get_channel(row["log_channel"])
        if ch is None:
            return
        e = embed(title, description, color)
        if user is not None:
            e.set_author(name=str(user), icon_url=user.display_avatar.url)
        try:
            await ch.send(embed=e)
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------ members
    @commands.Cog.listener()
    async def on_member_join(self, m):
        age = ts(m.created_at.timestamp())
        await self.record(m.guild, "join", "Member joined", f"{m.mention} joined. Account created {age}.", C.OK, m)
        if self.bot.db.is_quarantined(m.guild.id, m.id):  # re-quarantine evaders
            role_id = self.bot.db.get_guild(m.guild.id)["quarantine_role"]
            role = m.guild.get_role(role_id) if role_id else None
            if role:
                await m.add_roles(role, reason="Quarantine evasion (rejoined)")

    @commands.Cog.listener()
    async def on_member_remove(self, m):
        await self.record(m.guild, "leave", "Member left", f"{m.mention} (`{m.id}`) left or was removed.", C.WARN, m)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await self.record(guild, "ban", "Member banned", f"**{user}** (`{user.id}`) was banned.", C.BAD, user)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        await self.record(guild, "unban", "Member unbanned", f"**{user}** (`{user.id}`) was unbanned.", C.OK, user)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.nick != after.nick:
            await self.record(after.guild, "nick", "Nickname changed",
                              f"{after.mention}: `{before.nick}` → `{after.nick}`", C.INFO, after)
        added = set(after.roles) - set(before.roles)
        removed = set(before.roles) - set(after.roles)
        if added or removed:
            parts = [f"➕ {r.mention}" for r in added] + [f"➖ {r.mention}" for r in removed]
            await self.record(after.guild, "roles", "Roles changed", f"{after.mention}\n" + "\n".join(parts), C.INFO, after)
        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until:
                await self.record(after.guild, "timeout", "Member timed out",
                                  f"{after.mention} until {ts(after.timed_out_until.timestamp(), 'f')}", C.WARN, after)
            else:
                await self.record(after.guild, "untimeout", "Timeout removed", f"{after.mention}", C.OK, after)

    # ----------------------------------------------------------- messages
    @commands.Cog.listener()
    async def on_message_delete(self, msg):
        if msg.guild is None or msg.author.bot:
            return
        content = msg.content or "*no text (attachment/embed)*"
        await self.record(msg.guild, "msg_delete", "Message deleted",
                          f"In {msg.channel.mention}:\n{content[:1500]}", C.DARK, msg.author, msg.channel)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if after.guild is None or after.author.bot or before.content == after.content:
            return
        await self.record(after.guild, "msg_edit", "Message edited",
                          f"In {after.channel.mention} — [jump]({after.jump_url})\n"
                          f"**Before:** {before.content[:700] or '*empty*'}\n**After:** {after.content[:700] or '*empty*'}",
                          C.INFO, after.author, after.channel)

    # ----------------------------------------------------------- channels
    @commands.Cog.listener()
    async def on_guild_channel_create(self, ch):
        await self.record(ch.guild, "channel_create", "Channel created", f"{ch.mention} (`{ch.name}`)", C.OK)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, ch):
        await self.record(ch.guild, "channel_delete", "Channel deleted", f"`#{ch.name}`", C.BAD)

    # ----------------------------------------------------------- commands
    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        if ctx.guild:
            self.bot.db.log_event(ctx.guild.id, "command", ctx.author.id, ctx.channel.id, ctx.command.qualified_name)

    # ------------------------------------------------------------ viewing
    @commands.hybrid_command(name="auditlog", description="Browse the recent logged events for this server.")
    @commands.has_permissions(view_audit_log=True)
    @commands.guild_only()
    async def auditlog(self, ctx, event_type: str = None, member: discord.Member = None, limit: int = 15):
        rows = self.bot.db.recent_events(ctx.guild.id, min(max(limit, 1), 25), event_type, member.id if member else None)
        if not rows:
            return await ctx.send(embed=embed("Audit log", "Nothing logged yet.", C.DARK))
        lines = [f"{ts(r['created_at'], 't')} `{r['type']}` <@{r['user_id']}> — {(r['detail'] or '')[:80]}"
                 if r["user_id"] else f"{ts(r['created_at'], 't')} `{r['type']}` — {(r['detail'] or '')[:80]}"
                 for r in rows]
        await ctx.send(embed=embed("Audit log", "\n".join(lines)[:4000]))


async def setup(bot):
    await bot.add_cog(Logs(bot))
