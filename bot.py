import discord
from discord import app_commands
from discord.ext import commands
import datetime
import os
import json
import asyncio
import time
import re
import random
from collections import defaultdict, deque

# =========================================================
# 1. BOT SETTINGS
# =========================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="", intents=intents, case_insensitive=True)

# =========================================================
# 2. PER-SERVER CONFIG (saved in guild_config.json)
# =========================================================
# بۆ ئەوەی ڕێکخستنەکان لە Railway دوای ئەپدەیت/ڕیدیپلۆی نەسڕێنەوە:
#   1) لە Railway Volume دروست بکە و Mount Path بکە بە  /data
#   2) ئەگەر /data هەبێت بۆتەکە خۆکار لەوێ هەڵیدەگرێت
#   (یان Variable بەناوی CONFIG_PATH دابنێ)

if os.getenv("CONFIG_PATH"):
    CONFIG_FILE = os.getenv("CONFIG_PATH")
elif os.path.isdir("/data"):
    CONFIG_FILE = "/data/guild_config.json"
else:
    CONFIG_FILE = "guild_config.json"

LOG_TYPES = {
    "welcome": "Welcome",
    "server": "Server Log",
    "chat": "Chat Log",
    "voice": "Voice Log",
    "ban": "Ban Log",
    "left": "Left Log",
    "channel": "Channel Log",
    "role": "Role Log",
    "member": "Member Log",
    "nickname": "Nickname Log",
}

PERM_LABELS = {
    "mute": "Mute",
    "ban": "Ban (Bfra / Unban)",
    "safika": "Safika (Clear)",
    "staff": "Staff (/staff)",
}

# ناوی پیشاندراوی ستافەکان (value ەکان وەک خۆیان ماونەتەوە بۆ ئەوەی ڕێکخستنە کۆنەکان نەچن)
STAFF_LABELS = {
    "staff1": "Lady Staff",
    "staff2": "Boy Staff",
}

NO_PERM_TEXT = "To regat penadrawa ta ama bakar bhenit"

try:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
except Exception:
    config = {}


def save_config():
    try:
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_FILE)
    except Exception as e:
        print(f"save_config error: {e}")


def cfg(guild_id):
    d = config.setdefault(str(guild_id), {})
    d.setdefault("channels", {})       # welcome + log channels
    d.setdefault("roles", {})          # staff1, staff2
    d.setdefault("regri_roles", [])    # roles allowed to use /regri
    d.setdefault("restricted", [])     # users blocked from color change
    d.setdefault("color_roles", [])    # roles allowed to use /rangi-role (/regadan-ranggorin)
    d.setdefault("color_users", [])    # specific users allowed to use /rangi-role (/regadan-ranggorin)
    d.setdefault("welcome_text", "Baxer beyt")
    d.setdefault("welcome_image", None)  # image / gif link shown under the welcome text
    d.setdefault("dev_roles", [])      # developer roles (full control like owner)
    d.setdefault("mute_role", None)    # role given on mute (set with /setmuterole)
    d.setdefault("autorole", None)     # role given automatically to new members (/autorole)
    perm = d.setdefault("perm_roles", {})  # roles allowed: mute / ban / safika / staff
    for k in PERM_LABELS:
        perm.setdefault(k, [])
    return d


def has_cmd_access(member, key):
    """Owner + Administrator + roles chosen with /rolemute /roleban /rolesafika"""
    try:
        if member.id == member.guild.owner_id:
            return True
        if member.guild_permissions.administrator:
            return True
        allowed = cfg(member.guild.id)["perm_roles"].get(key, [])
        return any(r.id in allowed for r in member.roles)
    except Exception:
        return False


def is_dev(member):
    """Owner + roles chosen with /setdev (NOT every administrator)"""
    try:
        if member.id == member.guild.owner_id:
            return True
        dev = cfg(member.guild.id)["dev_roles"]
        return any(r.id in dev for r in member.roles)
    except Exception:
        return False


def has_staff_access(member):
    """Owner + developer roles + roles chosen with /rolestaff"""
    try:
        if is_dev(member):
            return True
        allowed = cfg(member.guild.id)["perm_roles"].get("staff", [])
        return any(r.id in allowed for r in member.roles)
    except Exception:
        return False


def has_color_access(member):
    """Owner + developer roles + roles/users chosen with /regadan-ranggorin"""
    try:
        if is_dev(member):
            return True
        c = cfg(member.guild.id)
        if member.id in c["color_users"]:
            return True
        return any(r.id in c["color_roles"] for r in member.roles)
    except Exception:
        return False


def get_mute_role(guild):
    """Role chosen with /setmuterole, otherwise a role named Muted"""
    rid = cfg(guild.id).get("mute_role")
    if rid:
        role = guild.get_role(rid)
        if role:
            return role
    return discord.utils.get(guild.roles, name="Muted")


def is_mute_role(role):
    try:
        rid = cfg(role.guild.id).get("mute_role")
        return role.name == "Muted" or (rid is not None and role.id == rid)
    except Exception:
        return role.name == "Muted"


def block_reason(guild, target, perm, role=None):
    """Explains exactly why Discord will refuse the action (or None if OK)."""
    me = guild.me
    if target.id == guild.owner_id:
        return "❌ خاوەنی سێرڤەر Ban/Mute ناکرێت (Discord ڕێگە نادات)."
    gp = me.guild_permissions
    if not (gp.administrator or getattr(gp, perm, False)):
        return f"❌ بۆتەکە مۆڵەتی `{perm}` ی نییە."
    if target.top_role >= me.top_role:
        return (
            f"❌ ڕۆڵی بۆتەکە (**{me.top_role.name}**) لە خوار یان یەکسانە لەگەڵ بەرزترین ڕۆڵی "
            f"**{target.display_name}** (**{target.top_role.name}**). "
            f"Discord ئەدمینی بۆتیش ڕێگە نادات. لە Server Settings ← Roles "
            f"ڕۆڵی **{me.top_role.name}** ڕابکێشە سەروو ڕۆڵی **{target.top_role.name}**."
        )
    if role is not None and role >= me.top_role:
        return (
            f"❌ ڕۆڵی Mute (**{role.name}**) لە سەروو یان یەکسانە لەگەڵ ڕۆڵی بۆتەکە (**{me.top_role.name}**). "
            f"ڕۆڵی بۆتەکە بەرزتر بکەرەوە لە Roles."
        )
    return None


def hierarchy_error(author, target):
    """Returns an error text if author may not act on target, else None."""
    guild = author.guild
    if target.id == author.id:
        return "❌ ناتوانیت ئەمە لەسەر خۆت بکەیت."
    if target.id == guild.owner_id:
        return "❌ ناتوانیت ئەمە لەسەر خاوەنی سێرڤەر بکەیت."
    if author.id == guild.owner_id or author.guild_permissions.administrator:
        return None
    if target.top_role >= author.top_role:
        return "❌ ناتوانیت ئەمە لەسەر کەسێک بکەیت کە ڕۆڵەکەی بەرزترە یان یەکسانە لەگەڵ ڕۆڵی تۆ."
    return None


# ---- "No permission" replies (stay 10 seconds, then disappear) ----

async def deny_interaction(interaction):
    """Slash command used without permission."""
    try:
        await interaction.response.send_message(NO_PERM_TEXT, delete_after=10)
    except Exception:
        pass


async def deny_message(message):
    """Text command (mute / safika / bfra ...) used without permission."""
    try:
        await message.channel.send(f"{message.author.mention} {NO_PERM_TEXT}", delete_after=10)
    except Exception:
        pass


def looks_like_command(message, parts, command):
    """True only when the message really looks like a command attempt,
    so normal chat that merely contains the word 'mute' does not get an error."""
    first = parts[0].lower()
    if first == command or (command == "safika" and first.startswith("safika")):
        return True
    return bool(message.mentions or message.reference)


# ---- Bans done by the bot's own commands (so the log shows the real moderator) ----
_recent_cmd_bans = {}   # (kind, user_id) -> (time, moderator mention)


def mark_cmd_ban(kind, user_id, by_mention):
    _recent_cmd_bans[(kind, user_id)] = (time.time(), by_mention)


def cmd_ban_by(kind, user_id):
    item = _recent_cmd_bans.get((kind, user_id))
    if item and time.time() - item[0] < 30:
        return item[1]
    return None


# ---- Role edits done by the bot's own commands (so the log shows the real person) ----
_recent_cmd_role_edits = {}   # role_id -> (time, user mention)


def mark_cmd_role_edit(role_id, by_mention):
    _recent_cmd_role_edits[role_id] = (time.time(), by_mention)


def cmd_role_edit_by(role_id):
    item = _recent_cmd_role_edits.get(role_id)
    if item and time.time() - item[0] < 30:
        return item[1]
    return None


# =========================================================
# 3. LOG HELPERS
# =========================================================

async def send_log(guild, key, embed):
    try:
        if guild is None:
            return
        channel_id = cfg(guild.id)["channels"].get(key)
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if channel is None:
            return
        await channel.send(embed=embed)
    except Exception:
        pass


def make_embed(title, description, color=discord.Color.blurple()):
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.set_footer(text="Server Logs")
    return embed


def add_user_thumbnail(embed, user):
    try:
        embed.set_thumbnail(url=user.display_avatar.url)
    except Exception:
        pass


# =========================================================
# 4. AUDIT LOG HELPER
# =========================================================

async def get_audit_executor(guild, action, target_id=None, delay=1.0):
    try:
        await asyncio.sleep(delay)
        async for entry in guild.audit_logs(limit=10, action=action):
            if target_id is not None:
                if entry.target is None or getattr(entry.target, "id", None) != target_id:
                    continue
            if entry.created_at:
                now = datetime.datetime.now(datetime.timezone.utc)
                if (now - entry.created_at).total_seconds() > 15:
                    continue
            return entry
    except Exception:
        pass
    return None


def who(entry, default="Unknown"):
    return entry.user.mention if entry and entry.user else default


# ---- Mute / Unmute log (shown in the Ban Log channel, with Ban / Timeout) ----
_recent_cmd_mutes = {}   # user_id -> time of a mute/unmute done by the bot's own commands


def mark_cmd_mute(user_id):
    """The bot's own mute/unmute commands log themselves (with the real moderator),
    so on_member_update must not log the same role change a second time."""
    _recent_cmd_mutes[user_id] = time.time()


async def log_mute_event(guild, target, by, muted, channel=None, via=None):
    lines = [
        f"**Member:** {target.mention}",
        f"**{'Muted' if muted else 'Unmuted'} By:** {by}",
    ]
    if channel is not None:
        lines.append(f"**Channel:** {channel.mention}")
    if via:
        lines.append(f"**Via:** {via}")

    embed = make_embed(
        "🔇 Member Muted" if muted else "🔈 Member Unmuted",
        "\n".join(lines),
        discord.Color.red() if muted else discord.Color.green()
    )
    add_user_thumbnail(embed, target)
    await send_log(guild, "ban", embed)


# =========================================================
# 5. READY
# =========================================================

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands", flush=True)
    except Exception as e:
        print(f"❌ Slash sync error: {e}", flush=True)

    for guild in bot.guilds:
        try:
            mute_role = get_mute_role(guild)
            if mute_role:
                await sync_muted_permissions(guild, mute_role)
        except Exception:
            pass

    print(f"بۆتەکە بە سەرکەوتوویی چالاک بوو وەک: {bot.user}", flush=True)
    print(f"Config file: {CONFIG_FILE}", flush=True)


# =========================================================
# 6. WELCOME + AUTOROLE
# =========================================================

@bot.event
async def on_member_join(member):
    c = cfg(member.guild.id)

    # ---- Autorole ----
    autorole_id = c.get("autorole")
    if autorole_id:
        auto_role = member.guild.get_role(autorole_id)
        if auto_role:
            try:
                await member.add_roles(auto_role, reason="Autorole")
            except Exception as e:
                print(f"autorole error: {e}")

    channel_id = c["channels"].get("welcome")
    channel = member.guild.get_channel(channel_id) if channel_id else None

    if channel:
        try:
            text = c["welcome_text"].replace("{server}", member.guild.name)
            embed = discord.Embed(
                title="WELCOME",
                description=f"{member.mention}\n{text}"
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            if c.get("welcome_image"):
                embed.set_image(url=c["welcome_image"])
            await channel.send(embed=embed)
        except Exception:
            pass

    embed = make_embed(
        "📥 Member Joined",
        f"**Member:** {member.mention}\n"
        f"**Username:** `{member}`\n"
        f"**ID:** `{member.id}`",
        discord.Color.green()
    )
    add_user_thumbnail(embed, member)
    await send_log(member.guild, "member", embed)


# =========================================================
# 7. MEMBER LEFT
# =========================================================

@bot.event
async def on_member_remove(member):
    embed = make_embed(
        "📤 Member Left",
        f"Member: {member.mention}\nUsername: {member}\nID: {member.id}",
        discord.Color.red()
    )
    add_user_thumbnail(embed, member)
    await send_log(member.guild, "left", embed)


# =========================================================
# 8. MEMBER UPDATE
# =========================================================

@bot.event
async def on_member_update(before, after):
    guild = after.guild

    if before.nick != after.nick:
        old_nick = before.nick if before.nick else before.name
        new_nick = after.nick if after.nick else after.name

        entry = await get_audit_executor(guild, discord.AuditLogAction.member_update, after.id)
        editor = who(entry, "Unknown / Self")

        embed = make_embed(
            "✏️ Nickname Changed",
            f"**Member:** {after.mention}\n"
            f"**Changed By:** {editor}\n"
            f"**Before:** `{old_nick}`\n"
            f"**After:** `{new_nick}`",
            discord.Color.gold()
        )
        add_user_thumbnail(embed, after)
        await send_log(guild, "nickname", embed)

    # ---- Discord Timeout (shown in the Ban Log channel) ----
    if before.timed_out_until != after.timed_out_until:
        entry = await get_audit_executor(guild, discord.AuditLogAction.member_update, after.id)
        by = who(entry)
        reason_line = f"\n**Reason:** {entry.reason}" if entry and entry.reason else ""

        if after.timed_out_until:
            ts = int(after.timed_out_until.timestamp())
            embed = make_embed(
                "⏳ Member Timed Out",
                f"**Member:** {after.mention}\n"
                f"**Timed Out By:** {by}\n"
                f"**Until:** <t:{ts}:F> (<t:{ts}:R>){reason_line}",
                discord.Color.orange()
            )
        else:
            embed = make_embed(
                "✅ Timeout Removed",
                f"**Member:** {after.mention}\n"
                f"**Removed By:** {by}{reason_line}",
                discord.Color.green()
            )
        add_user_thumbnail(embed, after)
        await send_log(guild, "ban", embed)

    # ---- Mute role given / removed by hand (not by the bot's own command) ----
    mute_role_obj = get_mute_role(guild)
    if mute_role_obj and (mute_role_obj in before.roles) != (mute_role_obj in after.roles):
        if time.time() - _recent_cmd_mutes.get(after.id, 0) > 10:
            entry = await get_audit_executor(guild, discord.AuditLogAction.member_role_update, after.id)
            await log_mute_event(
                guild, after, who(entry), mute_role_obj in after.roles, via="Role changed by hand"
            )

    added_roles = set(after.roles) - set(before.roles)
    removed_roles = set(before.roles) - set(after.roles)

    real_added = [r for r in added_roles if r.name != "@everyone" and not is_mute_role(r)]
    if real_added:
        entry = await get_audit_executor(guild, discord.AuditLogAction.member_role_update, after.id)
        roles_text = "\n".join(f"➕ {r.mention}" for r in real_added)
        embed = make_embed(
            "➕ Role Added",
            f"**Member:** {after.mention}\n"
            f"**Given By:** {who(entry)}\n\n{roles_text}",
            discord.Color.green()
        )
        add_user_thumbnail(embed, after)
        await send_log(guild, "member", embed)

    real_removed = [r for r in removed_roles if r.name != "@everyone" and not is_mute_role(r)]
    if real_removed:
        entry = await get_audit_executor(guild, discord.AuditLogAction.member_role_update, after.id)
        roles_text = "\n".join(f"➖ {r.mention}" for r in real_removed)
        embed = make_embed(
            "➖ Role Removed",
            f"**Member:** {after.mention}\n"
            f"**Removed By:** {who(entry)}\n\n{roles_text}",
            discord.Color.red()
        )
        add_user_thumbnail(embed, after)
        await send_log(guild, "member", embed)


# =========================================================
# 9. GET TARGET MEMBER FROM TAG OR REPLY
# =========================================================

async def get_target_member(message):
    if message.mentions:
        for member in message.mentions:
            if member.id != bot.user.id and isinstance(member, discord.Member):
                return member

    if message.reference:
        try:
            ref = message.reference.resolved
            if not isinstance(ref, discord.Message):
                ref = await message.channel.fetch_message(message.reference.message_id)
            if ref.author.id == bot.user.id:
                return None
            if isinstance(ref.author, discord.Member):
                return ref.author
            return message.guild.get_member(ref.author.id)
        except Exception:
            pass

    return None


# =========================================================
# 10. MUTED ROLE
# =========================================================

async def apply_muted_permissions(channel, mute_role):
    try:
        if isinstance(channel, (discord.TextChannel, discord.NewsChannel, discord.ForumChannel)):
            await channel.set_permissions(
                mute_role,
                send_messages=False,
                add_reactions=False,
                send_messages_in_threads=False,
                create_public_threads=False,
                create_private_threads=False,
                reason="Muted role - block chat"
            )
    except Exception:
        pass


async def sync_muted_permissions(guild, mute_role):
    for channel in guild.channels:
        await apply_muted_permissions(channel, mute_role)


async def get_or_create_muted_role(guild):
    mute_role = get_mute_role(guild)
    if not mute_role:
        mute_role = await guild.create_role(name="Muted", reason="Mute role")
    await sync_muted_permissions(guild, mute_role)
    return mute_role


# =========================================================
# 11. CHANNEL CREATE / DELETE / UPDATE LOG
# =========================================================

@bot.event
async def on_guild_channel_create(channel):
    try:
        mute_role = get_mute_role(channel.guild)
        if mute_role:
            await apply_muted_permissions(channel, mute_role)

        entry = await get_audit_executor(channel.guild, discord.AuditLogAction.channel_create, channel.id)

        embed = make_embed(
            "📁 Channel Created",
            f"**Channel:** {channel.mention}\n"
            f"**Name:** `{channel.name}`\n"
            f"**ID:** `{channel.id}`\n"
            f"**Type:** `{channel.type}`\n"
            f"**Created By:** {who(entry)}",
            discord.Color.green()
        )
        await send_log(channel.guild, "channel", embed)
    except Exception:
        pass


@bot.event
async def on_guild_channel_delete(channel):
    entry = await get_audit_executor(channel.guild, discord.AuditLogAction.channel_delete, channel.id)

    embed = make_embed(
        "🗑️ Channel Deleted",
        f"**Channel:** `#{channel.name}`\n"
        f"**ID:** `{channel.id}`\n"
        f"**Type:** `{channel.type}`\n"
        f"**Deleted By:** {who(entry)}",
        discord.Color.red()
    )
    await send_log(channel.guild, "channel", embed)


@bot.event
async def on_guild_channel_update(before, after):
    if before.category != after.category:
        try:
            mute_role = get_mute_role(after.guild)
            if mute_role:
                await apply_muted_permissions(after, mute_role)
        except Exception:
            pass

    changes = []

    if before.name != after.name:
        changes.append(f"**Name:** `{before.name}` → `{after.name}`")

    if before.category != after.category:
        old_c = before.category.name if before.category else "None"
        new_c = after.category.name if after.category else "None"
        changes.append(f"**Category:** `{old_c}` → `{new_c}`")

    if before.position != after.position:
        changes.append(f"**Position:** `{before.position}` → `{after.position}`")

    if changes:
        entry = await get_audit_executor(after.guild, discord.AuditLogAction.channel_update, after.id)
        embed = make_embed(
            "✏ Channel Updated",
            f"**Channel:** {after.mention}\n"
            f"**ID:** `{after.id}`\n"
            f"**Updated By:** {who(entry)}\n\n"
            + "\n".join(changes),
            discord.Color.gold()
        )
        await send_log(after.guild, "channel", embed)


# =========================================================
# 15. ROLE CREATE / DELETE / UPDATE
# =========================================================

@bot.event
async def on_guild_role_create(role):
    if is_mute_role(role):
        return

    entry = await get_audit_executor(role.guild, discord.AuditLogAction.role_create, role.id)
    embed = make_embed(
        "➕ Role Created",
        f"**Role:** {role.mention}\n"
        f"**Name:** `{role.name}`\n"
        f"**ID:** `{role.id}`\n"
        f"**Created By:** {who(entry)}",
        discord.Color.green()
    )
    await send_log(role.guild, "role", embed)


@bot.event
async def on_guild_role_delete(role):
    if is_mute_role(role):
        return

    entry = await get_audit_executor(role.guild, discord.AuditLogAction.role_delete, role.id)
    embed = make_embed(
        "🗑️ Role Deleted",
        f"**Role:** `{role.name}`\n"
        f"**ID:** `{role.id}`\n"
        f"**Deleted By:** {who(entry)}",
        discord.Color.red()
    )
    await send_log(role.guild, "role", embed)


@bot.event
async def on_guild_role_update(before, after):
    if is_mute_role(after):
        return

    changes = []

    if before.name != after.name:
        changes.append(f"**Name:** `{before.name}` → `{after.name}`")
    if before.color != after.color:
        changes.append(f"**Color:** `{before.color}` → `{after.color}`")
    if before.position != after.position:
        changes.append(f"**Position:** `{before.position}` → `{after.position}`")

    if changes:
        cmd_by = cmd_role_edit_by(after.id)
        if cmd_by:
            updated_by = cmd_by
            via_line = "**Via:** Bot command (/rangi-role)\n"
        else:
            entry = await get_audit_executor(after.guild, discord.AuditLogAction.role_update, after.id)
            updated_by = who(entry)
            via_line = ""
        embed = make_embed(
            "✏️ Role Updated",
            f"**Role:** {after.mention}\n"
            f"**ID:** `{after.id}`\n"
            f"**Updated By:** {updated_by}\n"
            f"{via_line}\n"
            + "\n".join(changes),
            discord.Color.gold()
        )
        await send_log(after.guild, "role", embed)


# =========================================================
# 18. VOICE LOG
# =========================================================

@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild

    # ---- Server Mute / Server Deafen (کەسێکی تر میوت یان دیفێنی کرد) ----
    if before.mute != after.mute or before.deaf != after.deaf:
        entry = await get_audit_executor(guild, discord.AuditLogAction.member_update, member.id)
        by = who(entry)
        ch = after.channel or before.channel
        ch_text = ch.mention if ch else "`—`"

        if before.mute != after.mute:
            if after.mute:
                embed = make_embed(
                    "🔇 Voice Muted",
                    f"**Member:** {member.mention}\n"
                    f"**Muted By:** {by}\n"
                    f"**Channel:** {ch_text}",
                    discord.Color.red()
                )
            else:
                embed = make_embed(
                    "🔈 Voice Unmuted",
                    f"**Member:** {member.mention}\n"
                    f"**Unmuted By:** {by}\n"
                    f"**Channel:** {ch_text}",
                    discord.Color.green()
                )
            add_user_thumbnail(embed, member)
            await send_log(guild, "voice", embed)

        if before.deaf != after.deaf:
            if after.deaf:
                embed = make_embed(
                    "🙉 Voice Deafened",
                    f"**Member:** {member.mention}\n"
                    f"**Deafened By:** {by}\n"
                    f"**Channel:** {ch_text}",
                    discord.Color.red()
                )
            else:
                embed = make_embed(
                    "👂 Voice Undeafened",
                    f"**Member:** {member.mention}\n"
                    f"**Undeafened By:** {by}\n"
                    f"**Channel:** {ch_text}",
                    discord.Color.green()
                )
            add_user_thumbnail(embed, member)
            await send_log(guild, "voice", embed)

    # ---- Join / Leave / Move ----
    if before.channel is None and after.channel is not None:
        embed = make_embed(
            "🔊 Voice Join",
            f"**Member:** {member.mention}\n**Channel:** {after.channel.mention}",
            discord.Color.green()
        )
    elif before.channel is not None and after.channel is None:
        embed = make_embed(
            "🔇 Voice Leave",
            f"**Member:** {member.mention}\n**Channel:** `{before.channel.name}`",
            discord.Color.red()
        )
    elif (
        before.channel is not None
        and after.channel is not None
        and before.channel.id != after.channel.id
    ):
        embed = make_embed(
            "🔀 Voice Move",
            f"**Member:** {member.mention}\n"
            f"**From:** `{before.channel.name}`\n"
            f"**To:** `{after.channel.name}`",
            discord.Color.gold()
        )
    else:
        return

    add_user_thumbnail(embed, member)
    await send_log(guild, "voice", embed)


# =========================================================
# 19 & 20. BAN / UNBAN LOG
# =========================================================

@bot.event
async def on_member_ban(guild, user):
    # ئەگەر بە کۆماندی Bfra بوو، ناوی ئەو کەسە دەنووسرێت کە نووسیویەتی (نەک بۆتەکە)
    by = cmd_ban_by("ban", user.id)
    if not by:
        entry = await get_audit_executor(guild, discord.AuditLogAction.ban, user.id)
        by = who(entry)

    embed = make_embed(
        "🔨 Member Banned",
        f"**Member:** {user.mention}\n**Banned By:** {by}",
        discord.Color.red()
    )
    add_user_thumbnail(embed, user)
    await send_log(guild, "ban", embed)


@bot.event
async def on_member_unban(guild, user):
    by = cmd_ban_by("unban", user.id)
    if not by:
        entry = await get_audit_executor(guild, discord.AuditLogAction.unban, user.id)
        by = who(entry)

    embed = make_embed(
        "♻ Member Unbanned",
        f"**Member:** {user.mention}\n**Unbanned By:** {by}",
        discord.Color.green()
    )
    add_user_thumbnail(embed, user)
    await send_log(guild, "ban", embed)


# =========================================================
# 21. SERVER UPDATE
# =========================================================

@bot.event
async def on_guild_update(before, after):
    changes = []

    if before.name != after.name:
        changes.append(f"**Server Name:** `{before.name}` → `{after.name}`")

    if changes:
        entry = await get_audit_executor(after, discord.AuditLogAction.guild_update)
        embed = make_embed(
            "⚙ Server Updated",
            f"**Updated By:** {who(entry)}\n\n" + "\n".join(changes),
            discord.Color.gold()
        )
        if after.icon:
            embed.set_thumbnail(url=after.icon.url)
        await send_log(after, "server", embed)


# =========================================================
# 22 & 23. MESSAGE DELETE / EDIT
# =========================================================

@bot.event
async def on_message_delete(message):
    if message.author.bot or message.guild is None:
        return

    content = message.content[:1500] if message.content else "*No text content*"

    embed = make_embed(
        "🗑️ Message Deleted",
        f"**Author:** {message.author.mention}\n"
        f"**Channel:** {message.channel.mention}\n\n"
        f"**Message:**\n```text\n{content}\n```",
        discord.Color.red()
    )
    add_user_thumbnail(embed, message.author)
    await send_log(message.guild, "chat", embed)


@bot.event
async def on_message_edit(before, after):
    if before.author.bot or before.guild is None or before.content == after.content:
        return

    old_content = before.content[:700] if before.content else "*Empty*"
    new_content = after.content[:700] if after.content else "*Empty*"

    embed = make_embed(
        "✏️ Message Edited",
        f"**Author:** {after.author.mention}\n"
        f"**Before:**\n```text\n{old_content}\n```\n"
        f"**After:**\n```text\n{new_content}\n```",
        discord.Color.gold()
    )
    add_user_thumbnail(embed, after.author)
    await send_log(after.guild, "chat", embed)


# =========================================================
# 24. MAIN COMMAND SYSTEM (no prefix)
# =========================================================

COMMAND_WORDS = ["safika", "mute", "unmute", "bfra", "unban", "lock", "unlock"]


def parse_safika_amount(parts):
    """Safika 1 / safika10 / safika ٥ / هەر شێوازێک"""
    for p in parts:
        pl = p.lower().strip()
        if pl.startswith("safika") and pl[6:].isdigit():
            return int(pl[6:])
    for p in parts:
        if p.strip().isdigit():
            return int(p.strip())
    return None


@bot.event
async def on_message(message):
    if message.author.bot or message.guild is None:
        return

    mute_role = get_mute_role(message.guild)

    if (
        mute_role
        and mute_role in message.author.roles
        and not message.author.guild_permissions.administrator
    ):
        try:
            await message.delete()
        except Exception:
            pass
        return

    content = message.content.strip()
    if not content:
        return

    parts = content.split()
    command = ""

    for part in parts:
        clean_part = part.lower().strip()
        if clean_part in COMMAND_WORDS:
            command = clean_part
            break
        if clean_part.startswith("safika") and clean_part[6:].isdigit():
            command = "safika"
            break

    if not command and parts:
        command = parts[0].lower()

    # ---------------- SAFIKA ----------------
    # (ئەمە تەنها کۆماندێکە کە نامەکان دەسڕێتەوە - چونکە کارەکەی ئەوەیە)
    if command == "safika":
        if not has_cmd_access(message.author, "safika"):
            if looks_like_command(message, parts, command):
                await deny_message(message)
            return

        amount = parse_safika_amount(parts)

        if amount is None or amount < 1:
            await message.channel.send("❌ وەک: `safika 10`", delete_after=5)
            return

        amount = min(amount, 1000)

        try:
            deleted = await message.channel.purge(limit=amount + 1)
            await message.channel.send(
                f"✅ `{max(len(deleted) - 1, 0)}` نامە سڕایەوە.", delete_after=3
            )
        except discord.Forbidden:
            await message.channel.send(
                "❌ بۆتەکە مۆڵەتی Manage Messages / Read Message History ی نییە.",
                delete_after=8
            )
        except Exception as e:
            print(f"safika error: {e}")
            await message.channel.send(f"❌ هەڵە: {e}", delete_after=8)
        return

    # ---------------- MUTE ----------------
    if command == "mute":
        if not has_cmd_access(message.author, "mute"):
            if looks_like_command(message, parts, command):
                await deny_message(message)
            return

        target = await get_target_member(message)
        if not target:
            await message.channel.send(
                "❌ کەسەکە تاگ بکە یان ڕیپلەی بکە: `mute @user`", delete_after=5
            )
            return

        err = hierarchy_error(message.author, target)
        if err:
            await message.channel.send(err, delete_after=5)
            return

        try:
            muted_role = await get_or_create_muted_role(message.guild)
            reason = block_reason(message.guild, target, "manage_roles", muted_role)
            if reason:
                await message.channel.send(reason, delete_after=15)
                return
            if muted_role not in target.roles:
                mark_cmd_mute(target.id)
                await target.add_roles(muted_role, reason=f"Muted by {message.author}")
                await log_mute_event(
                    message.guild, target, message.author.mention, True,
                    channel=message.channel, via="Bot command"
                )
            # نامەی تۆ و نامەی بۆتەکە هەردووکیان دەمێننەوە (هیچ دیلیتێک نییە)
            await message.channel.send(f"damt daxaa {target.mention}")
        except discord.Forbidden:
            await message.channel.send(
                "❌ بۆتەکە مۆڵەتی Manage Roles ی نییە، یان ڕۆڵی بۆتەکە لە **Roles** دا لە خوار ڕۆڵی Muted یان ئەو کەسەیە. ڕۆڵی بۆتەکە بەرز بکەرەوە.",
                delete_after=10
            )
        except Exception as e:
            print(f"mute error: {e}")
            await message.channel.send(f"❌ هەڵە: {e}", delete_after=8)
        return

    # ---------------- UNMUTE ----------------
    if command == "unmute":
        if not has_cmd_access(message.author, "mute"):
            if looks_like_command(message, parts, command):
                await deny_message(message)
            return

        target = await get_target_member(message)
        if not target:
            await message.channel.send(
                "❌ کەسەکە تاگ بکە یان ڕیپلەی بکە: `unmute @user`", delete_after=5
            )
            return

        try:
            muted_role = get_mute_role(message.guild)
            if muted_role and muted_role in target.roles:
                mark_cmd_mute(target.id)
                await target.remove_roles(muted_role)
                await log_mute_event(
                    message.guild, target, message.author.mention, False,
                    channel=message.channel, via="Bot command"
                )
            # نامەی تۆ و نامەی بۆتەکە هەردووکیان دەمێننەوە (هیچ دیلیتێک نییە)
            await message.channel.send(
                f"xwa xerm bnwse dllm basha aqllba amjara {target.mention}"
            )
        except discord.Forbidden:
            await message.channel.send(
                "❌ بۆتەکە مۆڵەتی Manage Roles ی نییە، یان ڕۆڵەکەی لە خوار ڕۆڵی Muted ە.",
                delete_after=10
            )
        except Exception as e:
            print(f"unmute error: {e}")
            await message.channel.send(f"❌ هەڵە: {e}", delete_after=8)
        return

    # ---------------- BFRA ----------------
    if command == "bfra":
        if not has_cmd_access(message.author, "ban"):
            if looks_like_command(message, parts, command):
                await deny_message(message)
            return

        target = await get_target_member(message)
        if not target:
            await message.channel.send(
                "❌ کەسەکە تاگ بکە یان ڕیپلەی بکە: `bfra @user`", delete_after=5
            )
            return

        err = hierarchy_error(message.author, target)
        if err:
            await message.channel.send(err, delete_after=5)
            return

        try:
            reason = block_reason(message.guild, target, "ban_members")
            if reason:
                await message.channel.send(reason, delete_after=15)
                return
            # ناوی ئەو کەسە لە لۆگ دەنووسرێت کە Bfra ی نووسیوە
            mark_cmd_ban("ban", target.id, message.author.mention)
            # چاتی کەسە باندکراوەکە ناسڕدرێتەوە
            await target.ban(reason=f"Banned by {message.author}", delete_message_seconds=0)
            # نامەی تۆ و نامەی بۆتەکە هەردووکیان دەمێننەوە (هیچ دیلیتێک نییە)
            await message.channel.send(f"Frenraa✈️ {target.mention}")
        except discord.Forbidden:
            await message.channel.send(
                "❌ بۆتەکە مۆڵەتی Ban Members ی نییە، یان ڕۆڵی بۆتەکە لە خوار ڕۆڵی ئەو کەسەیە. ڕۆڵی بۆتەکە بەرز بکەرەوە.",
                delete_after=10
            )
        except Exception as e:
            print(f"bfra error: {e}")
            await message.channel.send(f"❌ هەڵە: {e}", delete_after=8)
        return

    # ---------------- UNBAN ----------------
    if command == "unban":
        if not has_cmd_access(message.author, "ban"):
            if looks_like_command(message, parts, command):
                await deny_message(message)
            return

        user_id = None
        for p in parts:
            if p.strip().isdigit() and len(p.strip()) >= 15:
                user_id = int(p.strip())
                break

        if user_id is None:
            await message.channel.send("❌ وەک: `unban 123456789012345678`", delete_after=5)
            return

        try:
            user = await bot.fetch_user(user_id)
            mark_cmd_ban("unban", user_id, message.author.mention)
            await message.guild.unban(user)
            # نامەی تۆ و نامەی بۆتەکە هەردووکیان دەمێننەوە (هیچ دیلیتێک نییە)
            await message.channel.send("✅ Unban کرا.")
        except discord.NotFound:
            await message.channel.send("❌ ئەم کەسە لە لیستی Ban دا نییە.", delete_after=5)
        except discord.Forbidden:
            await message.channel.send("❌ بۆتەکە مۆڵەتی Ban Members ی نییە.", delete_after=8)
        except Exception as e:
            print(f"unban error: {e}")
            await message.channel.send(f"❌ هەڵە: {e}", delete_after=8)
        return

    # ---------------- LOCK ----------------
    if command == "lock":
        if not message.author.guild_permissions.manage_channels:
            return
        try:
            await message.channel.set_permissions(message.guild.default_role, send_messages=False)
            await message.channel.send("🔒 کەناڵەکە Lock کرا.")
        except Exception:
            pass
        return

    # ---------------- UNLOCK ----------------
    if command == "unlock":
        if not message.author.guild_permissions.manage_channels:
            return
        try:
            await message.channel.set_permissions(message.guild.default_role, send_messages=None)
            await message.channel.send("🔓 کەناڵەکە Unlock کرا.")
        except Exception:
            pass
        return


# =========================================================
# 25. SETUP SLASH COMMANDS (per server)
# =========================================================

@bot.tree.command(name="welcome", description="دیاریکردنی کەناڵی بەخێرهاتن")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    channel="کەناڵی بەخێرهاتن",
    text="دەقی بەخێرهاتن (دەتوانیت {server} بەکاربهێنیت)",
    image="لینکی ڕەسم یان گیف (بۆ لابردن بنووسە: off)"
)
async def welcome_cmd(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    text: str = None,
    image: str = None
):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return

    c = cfg(interaction.guild.id)
    c["channels"]["welcome"] = channel.id
    image_note = ""
    if image:
        img = image.strip()
        if img.lower() in ("off", "remove", "delete", "no", "none"):
            c["welcome_image"] = None
            image_note = "\n🖼 ڕەسم/گیف لابرا."
        elif img.lower().startswith(("http://", "https://")):
            c["welcome_image"] = img
            image_note = "\n🖼 ڕەسم/گیف دیاری کرا."
        else:
            await interaction.response.send_message(
                "❌ لینکی ڕەسم/گیف دەبێت بە `https://` دەست پێبکات.", ephemeral=True
            )
            return

    c["channels"]["welcome"] = channel.id
    if text:
        c["welcome_text"] = text
    save_config()

    await interaction.response.send_message(
        f"✅ کەناڵی بەخێرهاتن: {channel.mention}{image_note}", ephemeral=True
    )


@bot.tree.command(name="setlog", description="دیاریکردنی کەناڵی لۆگەکان")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(type="جۆری لۆگ", channel="کەناڵ")
@app_commands.choices(
    type=[app_commands.Choice(name=v, value=k) for k, v in LOG_TYPES.items() if k != "welcome"]
)
async def setlog(
    interaction: discord.Interaction,
    type: str,
    channel: discord.TextChannel
):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return

    cfg(interaction.guild.id)["channels"][type] = channel.id
    save_config()

    await interaction.response.send_message(
        f"✅ **{LOG_TYPES[type]}** → {channel.mention}", ephemeral=True
    )


@bot.tree.command(name="setlogall", description="هەموو لۆگەکان بخە یەک کەناڵەوە")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(channel="کەناڵی هەموو لۆگەکان")
async def setlogall(interaction: discord.Interaction, channel: discord.TextChannel):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return

    c = cfg(interaction.guild.id)
    for k in LOG_TYPES:
        if k != "welcome":
            c["channels"][k] = channel.id
    save_config()

    await interaction.response.send_message(
        f"✅ هەموو لۆگەکان → {channel.mention}", ephemeral=True
    )


@bot.tree.command(name="setstaff", description="دیاریکردنی ڕۆڵەکانی ستاف بۆ /staff")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(slot="جۆری ستاف", role="ڕۆڵەکە")
@app_commands.choices(
    slot=[
        app_commands.Choice(name="Lady Staff", value="staff1"),
        app_commands.Choice(name="Boy Staff", value="staff2"),
    ]
)
async def setstaff(interaction: discord.Interaction, slot: str, role: discord.Role):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return

    cfg(interaction.guild.id)["roles"][slot] = role.id
    save_config()

    await interaction.response.send_message(
        f"✅ {STAFF_LABELS.get(slot, slot)} → **{role.name}**", ephemeral=True
    )


@bot.tree.command(name="regri-roles", description="ڕۆڵەکانی ئەو کەسانەی دەتوانن /regri بەکاربهێنن")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(action="زیادکردن یان لابردن", role="ڕۆڵەکە")
@app_commands.choices(
    action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove"),
    ]
)
async def regri_roles(interaction: discord.Interaction, action: str, role: discord.Role):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return

    c = cfg(interaction.guild.id)

    if action == "add":
        if role.id not in c["regri_roles"]:
            c["regri_roles"].append(role.id)
        msg = f"✅ {role.mention} زیادکرا."
    else:
        if role.id in c["regri_roles"]:
            c["regri_roles"].remove(role.id)
        msg = f"✅ {role.mention} لابرا."

    save_config()
    await interaction.response.send_message(
        msg, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
    )


# ---------------------------------------------------------
# /rolemute  /roleban  /rolesafika  /rolestaff
# ---------------------------------------------------------

async def update_perm_role(interaction, key, action, role):
    user = interaction.user
    if not is_dev(user):
        await deny_interaction(interaction)
        return

    c = cfg(interaction.guild.id)
    lst = c["perm_roles"][key]

    if action == "add":
        if role.id not in lst:
            lst.append(role.id)
        msg = f"✅ {role.mention} ئێستا دەتوانێت **{PERM_LABELS[key]}** بەکاربهێنێت."
    elif action == "remove":
        if role.id in lst:
            lst.remove(role.id)
        msg = f"✅ {role.mention} لە **{PERM_LABELS[key]}** لابرا."
    else:
        msg = "❌ هەڵبژاردنێکی نادروستە."

    save_config()
    await interaction.response.send_message(
        msg, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
    )


PERM_ACTION_CHOICES = [
    app_commands.Choice(name="Add (زیادکردن)", value="add"),
    app_commands.Choice(name="Remove (لابردن)", value="remove"),
]


@bot.tree.command(name="rolemute", description="دیاریکردنی ئەو ڕۆڵانەی دەتوانن Mute بکەن")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(action="زیادکردن یان لابردن", role="ڕۆڵەکە")
@app_commands.choices(action=PERM_ACTION_CHOICES)
async def rolemute(interaction: discord.Interaction, action: str, role: discord.Role):
    await update_perm_role(interaction, "mute", action, role)


@bot.tree.command(name="roleban", description="دیاریکردنی ئەو ڕۆڵانەی دەتوانن Bfra / Unban بکەن")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(action="زیادکردن یان لابردن", role="ڕۆڵەکە")
@app_commands.choices(action=PERM_ACTION_CHOICES)
async def roleban(interaction: discord.Interaction, action: str, role: discord.Role):
    await update_perm_role(interaction, "ban", action, role)


@bot.tree.command(name="rolesafika", description="دیاریکردنی ئەو ڕۆڵانەی دەتوانن Safika (کلێر) بکەن")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(action="زیادکردن یان لابردن", role="ڕۆڵەکە")
@app_commands.choices(action=PERM_ACTION_CHOICES)
async def rolesafika(interaction: discord.Interaction, action: str, role: discord.Role):
    await update_perm_role(interaction, "safika", action, role)


@bot.tree.command(name="rolestaff", description="دیاریکردنی ئەو ڕۆڵانەی دەتوانن /staff بەکاربهێنن")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(action="زیادکردن یان لابردن", role="ڕۆڵەکە")
@app_commands.choices(action=PERM_ACTION_CHOICES)
async def rolestaff(interaction: discord.Interaction, action: str, role: discord.Role):
    await update_perm_role(interaction, "staff", action, role)


@bot.tree.command(name="setmuterole", description="دیاریکردنی ئەو ڕۆڵەی لە کاتی Mute دەدرێت بە کەسەکە")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(role="ڕۆڵی Mute (بۆ نموونە Muted)")
async def setmuterole(interaction: discord.Interaction, role: discord.Role):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return

    if role.is_default() or role.managed:
        await interaction.response.send_message(
            "❌ ئەم ڕۆڵە ناکرێت وەک ڕۆڵی Mute بەکاربێت.", ephemeral=True
        )
        return

    cfg(interaction.guild.id)["mute_role"] = role.id
    save_config()

    await interaction.response.defer(ephemeral=True)
    await sync_muted_permissions(interaction.guild, role)

    me = interaction.guild.me
    warn = ""
    if role >= me.top_role:
        warn = f"\n⚠ ڕۆڵی بۆتەکە (**{me.top_role.name}**) دەبێت لە سەروو ئەم ڕۆڵەوە بێت لە Roles."

    await interaction.followup.send(
        f"✅ ڕۆڵی Mute: **{role.name}** (ڕێگەپێدراوییەکانی هەموو کەناڵەکان ڕێکخرا).{warn}",
        ephemeral=True
    )


@bot.tree.command(name="autorole", description="دیاریکردنی ڕۆڵێک کە خۆکارانە بدرێت بە ئەندامی نوێ")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(action="دانان یان لابردن", role="ڕۆڵەکە (بۆ Set پێویستە)")
@app_commands.choices(
    action=[
        app_commands.Choice(name="Set (دانان)", value="set"),
        app_commands.Choice(name="Off (لابردن)", value="off"),
    ]
)
async def autorole_cmd(interaction: discord.Interaction, action: str, role: discord.Role = None):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return

    c = cfg(interaction.guild.id)

    if action == "off":
        c["autorole"] = None
        save_config()
        await interaction.response.send_message("✅ Autorole لابرا.", ephemeral=True)
        return

    if role is None:
        await interaction.response.send_message(
            "❌ ڕۆڵەکە دیاری بکە: `/autorole set @role`", ephemeral=True
        )
        return

    if role.is_default() or role.managed:
        await interaction.response.send_message(
            "❌ ئەم ڕۆڵە ناکرێت وەک Autorole بەکاربێت.", ephemeral=True
        )
        return

    c["autorole"] = role.id
    save_config()

    warn = ""
    me = interaction.guild.me
    if role >= me.top_role:
        warn = f"\n⚠ ڕۆڵی بۆتەکە (**{me.top_role.name}**) دەبێت لە سەروو ئەم ڕۆڵەوە بێت لە Roles، دەنا نایدات."

    await interaction.response.send_message(
        f"✅ Autorole: {role.mention} — ئەندامی نوێ خۆکارانە ئەم ڕۆڵە وەردەگرێت.{warn}",
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none()
    )


@bot.tree.command(name="setdev", description="دیاریکردنی ڕۆڵی دیڤیلۆپەر (تەنها خاوەنی سێرڤەر)")
@app_commands.guild_only()
@app_commands.describe(action="زیادکردن یان لابردن", role="ڕۆڵی دیڤیلۆپەر")
@app_commands.choices(action=PERM_ACTION_CHOICES)
async def setdev(interaction: discord.Interaction, action: str, role: discord.Role):
    if interaction.user.id != interaction.guild.owner_id:
        await deny_interaction(interaction)
        return

    c = cfg(interaction.guild.id)

    if action == "add":
        if role.id not in c["dev_roles"]:
            c["dev_roles"].append(role.id)
        msg = f"✅ {role.mention} بوو بە ڕۆڵی دیڤیلۆپەر."
    else:
        if role.id in c["dev_roles"]:
            c["dev_roles"].remove(role.id)
        msg = f"✅ {role.mention} لە ڕۆڵی دیڤیلۆپەر لابرا."

    save_config()
    await interaction.response.send_message(
        msg, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
    )


@bot.tree.command(name="config", description="پیشاندانی ڕێکخستنەکانی ئەم سێرڤەرە")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
async def config_cmd(interaction: discord.Interaction):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return

    c = cfg(interaction.guild.id)
    lines = []

    for k, name in LOG_TYPES.items():
        cid = c["channels"].get(k)
        lines.append(f"**{name}:** {f'<#{cid}>' if cid else '❌'}")

    for slot in ("staff1", "staff2"):
        rid = c["roles"].get(slot)
        lines.append(f"**{STAFF_LABELS[slot]}:** {f'<@&{rid}>' if rid else '❌'}")

    regri_txt = ", ".join(f"<@&{r}>" for r in c["regri_roles"]) or "❌"
    lines.append(f"**Regri roles:** {regri_txt}")

    color_roles_txt = ", ".join(f"<@&{r}>" for r in c["color_roles"]) or "❌"
    color_users_txt = ", ".join(f"<@{u}>" for u in c["color_users"]) or "❌"
    lines.append(f"**Color roles:** {color_roles_txt}")
    lines.append(f"**Color users:** {color_users_txt}")

    dev = ", ".join(f"<@&{r}>" for r in c["dev_roles"]) or "❌ (تەنها Owner)"
    lines.append(f"**Developer roles:** {dev}")

    mrid = c.get("mute_role")
    lines.append(f"**Mute role:** {f'<@&{mrid}>' if mrid else '❌ (Muted بە ناو)'}")

    arid = c.get("autorole")
    lines.append(f"**Autorole:** {f'<@&{arid}>' if arid else '❌'}")

    for k, label in PERM_LABELS.items():
        roles_txt = ", ".join(f"<@&{r}>" for r in c["perm_roles"][k]) or "❌"
        lines.append(f"**{label} roles:** {roles_txt}")

    await interaction.response.send_message(
        "\n".join(lines),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none()
    )


# =========================================================
# 26. STAFF
# =========================================================

@bot.tree.command(name="staff", description="پێدانی ڕۆڵی ستاف بە ئەندام")
@app_commands.guild_only()
@app_commands.choices(
    role_choice=[
        app_commands.Choice(name="Lady Staff", value="staff1"),
        app_commands.Choice(name="Boy Staff", value="staff2"),
    ]
)
async def staff(
    interaction: discord.Interaction,
    member: discord.Member,
    role_choice: str
):
    if not has_staff_access(interaction.user):
        await deny_interaction(interaction)
        return

    try:
        role_id = cfg(interaction.guild.id)["roles"].get(role_choice)
        role = interaction.guild.get_role(role_id) if role_id else None

        if not role:
            await interaction.response.send_message(
                "❌ ڕۆڵەکە دیاری نەکراوە! سەرەتا /setstaff بەکاربهێنە.", ephemeral=True
            )
            return

        if role in member.roles:
            await interaction.response.send_message(
                f"⚠ {member.mention} پێشتر ئەم ڕۆڵەی هەیە (`{role.name}`).", ephemeral=True
            )
        else:
            await member.add_roles(role, reason=f"Staff given by {interaction.user}")
            await interaction.response.send_message(
                f"✅ ڕۆڵی **{role.name}** بە سەرکەوتوویی درا بە {member.mention}",
                ephemeral=True
            )

    except Exception as e:
        await interaction.response.send_message(f"❌ کێشەیەک ڕوویدا: {e}", ephemeral=True)


# =========================================================
# 27. COLOR ROLE SYSTEM
# =========================================================

@bot.tree.command(
    name="regadan-ranggorin",
    description="ڕێگەپێدانی ڕۆڵ یان کەس بۆ گۆڕینی ڕەنگی ڕۆڵ"
)
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    action="زیادکردن یان لابردن",
    role="ڕۆڵێک کە ڕێگەی پێبدرێت (ئارەزوومەندانە)",
    member="کەسێکی تایبەت کە ڕێگەی پێبدرێت (ئارەزوومەندانە)"
)
@app_commands.choices(action=PERM_ACTION_CHOICES)
async def regadan_ranggorin(
    interaction: discord.Interaction,
    action: str,
    role: discord.Role = None,
    member: discord.Member = None
):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return

    if role is None and member is None:
        await interaction.response.send_message(
            "❌ دەبێت ڕۆڵێک یان کەسێک دیاری بکەیت.", ephemeral=True
        )
        return

    c = cfg(interaction.guild.id)
    lines = []

    if role is not None:
        if action == "add":
            if role.id not in c["color_roles"]:
                c["color_roles"].append(role.id)
            lines.append(f"✅ {role.mention} ئێستا دەتوانێت ڕەنگی ڕۆڵ بگۆڕێت.")
        else:
            if role.id in c["color_roles"]:
                c["color_roles"].remove(role.id)
            lines.append(f"✅ {role.mention} لە ڕێگەپێدانی ڕەنگ لابرا.")

    if member is not None:
        if action == "add":
            if member.id not in c["color_users"]:
                c["color_users"].append(member.id)
            lines.append(f"✅ {member.mention} ئێستا دەتوانێت ڕەنگی ڕۆڵ بگۆڕێت.")
        else:
            if member.id in c["color_users"]:
                c["color_users"].remove(member.id)
            lines.append(f"✅ {member.mention} لە ڕێگەپێدانی ڕەنگ لابرا.")

    save_config()
    await interaction.response.send_message(
        "\n".join(lines),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none()
    )


def parse_hex_color(text):
    """'#FF0000' / 'ff0000' / '#f00' -> discord.Color, or None if invalid."""
    h = text.strip().lstrip("#")
    if len(h) == 3 and all(ch in "0123456789abcdefABCDEF" for ch in h):
        h = "".join(ch * 2 for ch in h)
    if len(h) != 6 or not all(ch in "0123456789abcdefABCDEF" for ch in h):
        return None
    return discord.Color(int(h, 16))


@bot.tree.command(name="rangi-role", description="گۆڕینی ڕەنگی ڕۆڵ")
@app_commands.guild_only()
@app_commands.describe(
    role="ڕۆڵەکە هەڵبژێرە",
    color="کۆدی ڕەنگ بۆ نموونە #FF0000"
)
async def rangi_role(interaction: discord.Interaction, role: discord.Role, color: str):
    if not has_color_access(interaction.user):
        await deny_interaction(interaction)
        return

    guild = interaction.guild

    if interaction.user.id in cfg(guild.id)["restricted"]:
        await interaction.response.send_message(
            "❌ تۆ قەدەغەکراوی لە گۆڕینی ڕەنگ!", ephemeral=True
        )
        return

    target_role = role

    user_top_role = interaction.user.top_role
    is_owner = interaction.user.id == guild.owner_id

    if (
        target_role.is_default()
        or target_role.managed
        or target_role.is_bot_managed()
    ):
        await interaction.response.send_message(
            "❌ ناتوانیت ڕەنگی ئەم ڕۆڵە بگۆڕیت!", ephemeral=True
        )
        return

    if not is_owner and target_role > user_top_role:
        await interaction.response.send_message(
            "❌ ناتوانیت ڕەنگی ئەم ڕۆڵە بگۆڕیت چونکە لەسەروو ڕۆڵەکەتدایە!",
            ephemeral=True
        )
        return

    me = guild.me
    if target_role >= me.top_role:
        await interaction.response.send_message(
            f"❌ ڕۆڵی بۆتەکە (**{me.top_role.name}**) دەبێت لە سەروو ڕۆڵی **{target_role.name}** بێت. "
            f"لە Server Settings ← Roles ڕۆڵی بۆتەکە بەرز بکەرەوە.",
            ephemeral=True
        )
        return

    color_obj = parse_hex_color(color)
    if color_obj is None:
        await interaction.response.send_message(
            "❌ کۆدی ڕەنگ هەڵەیە. نموونە: `#FF0000`", ephemeral=True
        )
        return

    try:
        mark_cmd_role_edit(target_role.id, interaction.user.mention)
        await target_role.edit(
            color=color_obj,
            reason=f"Color changed by {interaction.user}"
        )
        await interaction.response.send_message(
            f"✅ ڕەنگی ڕۆڵی **{target_role.name}** بە سەرکەوتوویی گۆڕدرا!",
            ephemeral=True
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ بۆتەکە مۆڵەتی **Manage Roles** ی نییە، یان ڕۆڵەکەی لە خوار ئەم ڕۆڵەیە.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ هەڵە ڕوویدا: {e}", ephemeral=True)


# =========================================================
# 28. REGRI
# =========================================================

@bot.tree.command(name="regri", description="قەدەغەکردن یان لابردنی قەدەغەی گۆڕینی ڕەنگ")
@app_commands.guild_only()
@app_commands.choices(
    action=[
        app_commands.Choice(name="Add (قەدەغەکردن)", value="add"),
        app_commands.Choice(name="Remove (ڕێگەپێدان)", value="remove"),
    ]
)
async def regri(interaction: discord.Interaction, member: discord.Member, action: str):
    c = cfg(interaction.guild.id)

    is_owner = interaction.user.id == interaction.guild.owner_id
    has_allowed_role = any(r.id in c["regri_roles"] for r in interaction.user.roles)

    if not is_owner and not has_allowed_role:
        await deny_interaction(interaction)
        return

    if action.lower() == "add":
        if member.id not in c["restricted"]:
            c["restricted"].append(member.id)
        save_config()
        await interaction.response.send_message(
            f"🚫 {member.mention} قەدەغەکرا لە گۆڕینی ڕەنگ.", ephemeral=True
        )
    else:
        if member.id in c["restricted"]:
            c["restricted"].remove(member.id)
        save_config()
        await interaction.response.send_message(
            f"✅ ڕێگەدرا بە {member.mention} بۆ گۆڕینی ڕەنگ.", ephemeral=True
        )


# =========================================================
# 29. SECURITY SYSTEM  (/security)
# =========================================================
# Anti-Spam / Anti-Mention / Anti-Invite / Anti-Link
# Anti-Nuke: Channel + Role create/delete/rename/permissions, Ban, Kick, Bot Add
# هەموو Limit و چرکە و ماوەی Timeout لە /security دەستکاری دەکرێن.

# key: (label, default_enabled, default_limit, default_seconds, default_timeout_min, hint)
SEC_MODULES = {
    "spam": ("Anti-Spam", True, 5, 5, 10,
             "Limit = چەند نامە ڕێگەپێدراوە لە Seconds چرکەدا. زیاتر بنێرێت = سزا + سڕینەوەی نامەکان"),
    "mention": ("Anti-Mention", True, 5, 0, 10,
                "Limit = زۆرترین تاگ لە یەک نامەدا (Seconds بەکارنایەت)"),
    "invite": ("Anti-Invite", True, 1, 60, 30,
               "Limit = چەند لینکی بانگهێشت ڕێگەپێدراوە لە Seconds چرکەدا"),
    "link": ("Anti-Link", False, 2, 30, 10,
             "Limit = چەند لینک ڕێگەپێدراوە لە Seconds چرکەدا"),
    "chan_create": ("Channel Create", True, 2, 60, 60, "چەند چەناڵ دروست بکرێت لە Seconds چرکەدا"),
    "chan_delete": ("Channel Delete", True, 2, 60, 60, "چەند چەناڵ بسڕدرێتەوە لە Seconds چرکەدا"),
    "chan_name": ("Channel Rename", True, 3, 60, 60, "چەند جار ناوی چەناڵ بگۆڕدرێت"),
    "chan_perm": ("Channel Permissions", True, 3, 60, 60, "چەند جار پێرمشنی چەناڵ بگۆڕدرێت"),
    "role_create": ("Role Create", True, 2, 60, 60, "چەند ڕۆڵ دروست بکرێت"),
    "role_delete": ("Role Delete", True, 2, 60, 60, "چەند ڕۆڵ بسڕدرێتەوە"),
    "role_name": ("Role Rename", True, 3, 60, 60, "چەند جار ناوی ڕۆڵ بگۆڕدرێت"),
    "role_perm": ("Role Permissions", True, 3, 60, 60, "چەند جار پێرمشنی ڕۆڵ بگۆڕدرێت"),
    "ban": ("Anti-Ban", True, 2, 60, 60, "چەند کەس Ban بکرێن"),
    "kick": ("Anti-Kick", True, 2, 60, 60, "چەند کەس Kick بکرێن"),
    "bot_add": ("Anti-Bot Add", True, 0, 60, 60, "Limit 0 = هەر بۆتێک زیاد بکرێت، بۆتەکە دەردەکرێت و زیادکەرەکە سزا دەدرێت"),
}

# تەنها ئەم بەشانە ڕۆڵەکان لادەبەن (دەتوانیت لە /security بۆ هەر بەشێک بیگۆڕیت)
SEC_ROLE_REMOVE_DEFAULT = {"chan_delete", "ban", "kick"}

SEC_PUNISH_ORDER = ["timeout", "kick", "ban", "none"]
SEC_PUNISH_LABELS = {"timeout": "Timeout", "kick": "Kick", "ban": "Ban", "none": "Warning only"}

SEC_INVITE_RX = re.compile(r"(discord\.gg|discord(?:app)?\.com/invite)/[\w-]+", re.I)
SEC_LINK_RX = re.compile(r"https?://\S+", re.I)

_sec_hits = defaultdict(deque)
_sec_details = defaultdict(list)
_sec_spam = defaultdict(deque)


def get_sec(gid):
    c = cfg(gid)
    s = c.setdefault("security", {})
    s.setdefault("enabled", True)
    s.setdefault("log_channel", None)     # warning channel (chosen in /security)
    s.setdefault("punish", "timeout")
    s.setdefault("remove_roles", True)
    s.setdefault("wl_users", [])
    s.setdefault("wl_roles", [])
    mods = s.setdefault("modules", {})
    for k, (_, en, lim, sec, tmo, _) in SEC_MODULES.items():
        m = mods.setdefault(k, {"enabled": en, "limit": lim, "seconds": sec, "timeout": tmo})
        m.setdefault("timeout", tmo)
        m.setdefault("remove_roles", k in SEC_ROLE_REMOVE_DEFAULT)
    return s


def sec_mod_on(guild, key):
    s = get_sec(guild.id)
    return s["enabled"] and s["modules"][key]["enabled"]


def sec_exempt(guild, user_id):
    """Bot itself, owner, developer roles (/setdev) and the whitelist are never punished."""
    if user_id == bot.user.id or user_id == guild.owner_id:
        return True
    s = get_sec(guild.id)
    if user_id in s["wl_users"]:
        return True
    m = guild.get_member(user_id)
    if m is None:
        return False
    if is_dev(m):
        return True
    return any(r.id in s["wl_roles"] for r in m.roles)


async def sec_audit(guild, actions, target_id):
    await asyncio.sleep(1.0)
    for action in actions:
        try:
            async for entry in guild.audit_logs(limit=6, action=action):
                if getattr(entry.target, "id", None) != target_id:
                    continue
                age = (datetime.datetime.now(datetime.timezone.utc) - entry.created_at).total_seconds()
                if age > 15:
                    continue
                return entry
        except Exception:
            pass
    return None


def sec_executor_id(entry, ban_kind=None, target_id=None):
    uid = entry.user.id if entry and entry.user else None
    if uid == bot.user.id and ban_kind:
        by = cmd_ban_by(ban_kind, target_id)   # ban done with the bot's own "bfra" command
        if by:
            found = re.search(r"\d+", by)
            if found:
                return int(found.group())
    return uid


def sec_add_detail(gid, uid, text):
    lst = _sec_details[(gid, uid)]
    lst.append(text)
    del lst[:-10]


async def sec_send_warning(guild, embed):
    try:
        s = get_sec(guild.id)
        cid = s.get("log_channel") or cfg(guild.id)["channels"].get("server")
        ch = guild.get_channel(cid) if cid else None
        if ch:
            await ch.send(embed=embed)
    except Exception:
        pass


async def sec_punish(guild, uid, key, count):
    s = get_sec(guild.id)
    m = s["modules"][key]
    label = SEC_MODULES[key][0]
    results = []

    member = guild.get_member(uid)
    if member is None:
        try:
            member = await guild.fetch_member(uid)
        except Exception:
            member = None

    if member is None:
        results.append("⚠ ئەندامەکە لە سێرڤەر نەماوە.")
    else:
        me = guild.me
        reason = f"Security: {label}"

        # ---- remove roles ----
        if m["remove_roles"]:
            roles = [r for r in member.roles
                     if not r.is_default() and not r.managed and r < me.top_role]
            if roles:
                try:
                    await member.remove_roles(*roles, reason=reason)
                    results.append("✅ ڕۆڵەکانی لابرا: " + ", ".join(f"`{r.name}`" for r in roles))
                except Exception:
                    results.append("❌ نەتوانرا ڕۆڵەکان لابدرێن (ڕۆڵی بۆتەکە بەرز بکەرەوە).")
            else:
                results.append("ℹ️ ڕۆڵێک نەبوو بۆ لابردن.")
        else:
            results.append("ℹ️ لابردنی ڕۆڵ بۆ ئەم بەشە OFF ـە.")

        # ---- timeout / kick / ban ----
        p = s["punish"]
        try:
            if p == "timeout":
                mins = max(1, min(int(m["timeout"]), 40320))
                await member.timeout(datetime.timedelta(minutes=mins), reason=reason)
                results.append(f"✅ Timeout بۆ `{mins}` خولەک.")
            elif p == "kick":
                await member.kick(reason=reason)
                results.append("✅ Kick کرا.")
            elif p == "ban":
                await member.ban(reason=reason, delete_message_seconds=0)
                results.append("✅ Ban کرا.")
        except Exception:
            results.append(f"❌ نەتوانرا `{SEC_PUNISH_LABELS[p]}` بکرێت (مۆڵەت / ڕۆڵی بۆتەکە).")

    details = _sec_details.pop((guild.id, uid), [])
    window = f"لە `{m['seconds']}` چرکەدا" if m["seconds"] > 0 else "لە یەک نامەدا"
    embed = discord.Embed(
        title="🛡️ Security Warning",
        description=(
            f"**Member:** <@{uid}>\n"
            f"**بەش:** {label}\n\n"
            f"**هۆکاری سزا:**\n"
            f"ئەم ئەندامە {window} `{count}` جار ئەم کارەی کرد، لە کاتێکدا Limit ـەکە `{m['limit']}` ـە.\n\n"
            f"**چی کرد:**\n" + ("\n".join(details) or "—") +
            "\n\n**سزا:**\n" + "\n".join(results)
        ),
        color=discord.Color.red(),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    embed.set_footer(text="Security")
    if member:
        add_user_thumbnail(embed, member)
    await sec_send_warning(guild, embed)


async def sec_register(guild, uid, key, what):
    """Count one action. Returns True if the user was punished."""
    if uid is None or not sec_mod_on(guild, key) or sec_exempt(guild, uid):
        return False
    m = get_sec(guild.id)["modules"][key]
    sec_add_detail(guild.id, uid, what)
    dq = _sec_hits[(guild.id, uid, key)]
    now = time.time()
    dq.append(now)
    if m["seconds"] > 0:
        while dq and now - dq[0] > m["seconds"]:
            dq.popleft()
    if len(dq) > m["limit"]:
        n = len(dq)
        dq.clear()
        await sec_punish(guild, uid, key, n)
        return True
    return False


# ---------------------------------------------------------
# message protection
# ---------------------------------------------------------

async def sec_safe_delete(message):
    try:
        await message.delete()
    except Exception:
        pass


async def sec_on_message(message):
    if message.author.bot or message.guild is None:
        return

    guild = message.guild
    s = get_sec(guild.id)
    if not s["enabled"] or sec_exempt(guild, message.author.id):
        return

    uid = message.author.id
    mods = s["modules"]
    text = message.content or ""

    # ---- mention spam ----
    if mods["mention"]["enabled"]:
        cnt = len(message.mentions) + len(message.role_mentions) + (1 if message.mention_everyone else 0)
        if cnt > mods["mention"]["limit"]:
            await sec_safe_delete(message)
            sec_add_detail(guild.id, uid, f"📢 {cnt} تاگی کرد لە یەک نامەدا لە {message.channel.mention}")
            await sec_punish(guild, uid, "mention", cnt)
            return

    # ---- invite / link ----
    for key, rx in (("invite", SEC_INVITE_RX), ("link", SEC_LINK_RX)):
        if mods[key]["enabled"] and rx.search(text):
            await sec_safe_delete(message)
            done = await sec_register(
                guild, uid, key,
                f"🔗 {SEC_MODULES[key][0]}: لینکی نارد لە {message.channel.mention}"
            )
            if not done:
                try:
                    await message.channel.send(
                        f"⚠ {message.author.mention} نابێت لینک بنێریت.", delete_after=6)
                except Exception:
                    pass
            return

    # ---- message spam ----
    m = mods["spam"]
    if m["enabled"]:
        now = time.time()
        dq = _sec_spam[(guild.id, uid)]
        dq.append((now, message))
        while dq and now - dq[0][0] > m["seconds"]:
            dq.popleft()
        if len(dq) > m["limit"]:
            msgs = [x[1] for x in dq]
            dq.clear()
            by_ch = defaultdict(list)
            for x in msgs:
                by_ch[x.channel].append(x)
            for ch, lst in by_ch.items():
                try:
                    await ch.delete_messages(lst)
                except Exception:
                    pass
            sec_add_detail(guild.id, uid, f"💬 {len(msgs)} نامەی نارد لە {m['seconds']} چرکەدا")
            await sec_punish(guild, uid, "spam", len(msgs))


# ---------------------------------------------------------
# anti-nuke events
# ---------------------------------------------------------

async def sec_on_channel_create(channel):
    g = channel.guild
    if not sec_mod_on(g, "chan_create"):
        return
    entry = await sec_audit(g, [discord.AuditLogAction.channel_create], channel.id)
    if entry and entry.user:
        await sec_register(g, entry.user.id, "chan_create", f"📁 چەناڵی `{channel.name}` دروست کرد")


async def sec_on_channel_delete(channel):
    g = channel.guild
    if not sec_mod_on(g, "chan_delete"):
        return
    entry = await sec_audit(g, [discord.AuditLogAction.channel_delete], channel.id)
    if entry and entry.user:
        await sec_register(g, entry.user.id, "chan_delete", f"🗑️ چەناڵی `#{channel.name}` سڕییەوە")


async def sec_on_channel_update(before, after):
    g = after.guild
    if before.name != after.name and sec_mod_on(g, "chan_name"):
        entry = await sec_audit(g, [discord.AuditLogAction.channel_update], after.id)
        if entry and entry.user:
            await sec_register(g, entry.user.id, "chan_name",
                               f"✏️ ناوی چەناڵی `{before.name}` گۆڕی بۆ `{after.name}`")
    if before.overwrites != after.overwrites and sec_mod_on(g, "chan_perm"):
        entry = await sec_audit(g, [discord.AuditLogAction.overwrite_update,
                                    discord.AuditLogAction.overwrite_create,
                                    discord.AuditLogAction.overwrite_delete], after.id)
        if entry and entry.user:
            await sec_register(g, entry.user.id, "chan_perm",
                               f"🔐 پێرمشنی چەناڵی {after.mention} گۆڕی")


async def sec_on_role_create(role):
    g = role.guild
    if role.managed or not sec_mod_on(g, "role_create"):
        return
    entry = await sec_audit(g, [discord.AuditLogAction.role_create], role.id)
    if entry and entry.user:
        await sec_register(g, entry.user.id, "role_create", f"➕ ڕۆڵی `{role.name}` دروست کرد")


async def sec_on_role_delete(role):
    g = role.guild
    if role.managed or not sec_mod_on(g, "role_delete"):
        return
    entry = await sec_audit(g, [discord.AuditLogAction.role_delete], role.id)
    if entry and entry.user:
        await sec_register(g, entry.user.id, "role_delete", f"🗑️ ڕۆڵی `{role.name}` سڕییەوە")


async def sec_on_role_update(before, after):
    g = after.guild
    if after.managed:
        return
    if before.name != after.name and sec_mod_on(g, "role_name"):
        entry = await sec_audit(g, [discord.AuditLogAction.role_update], after.id)
        if entry and entry.user:
            await sec_register(g, entry.user.id, "role_name",
                               f"✏️ ناوی ڕۆڵی `{before.name}` گۆڕی بۆ `{after.name}`")
    if before.permissions != after.permissions and sec_mod_on(g, "role_perm"):
        entry = await sec_audit(g, [discord.AuditLogAction.role_update], after.id)
        if entry and entry.user:
            await sec_register(g, entry.user.id, "role_perm",
                               f"🔐 پێرمشنی ڕۆڵی `{after.name}` گۆڕی")


async def sec_on_ban(guild, user):
    if not sec_mod_on(guild, "ban"):
        return
    entry = await sec_audit(guild, [discord.AuditLogAction.ban], user.id)
    uid = sec_executor_id(entry, "ban", user.id)
    if uid:
        await sec_register(guild, uid, "ban", f"🔨 {user} (`{user.id}`) ی Ban کرد")


async def sec_on_member_remove(member):
    g = member.guild
    if not sec_mod_on(g, "kick"):
        return
    entry = await sec_audit(g, [discord.AuditLogAction.kick], member.id)
    if entry and entry.user:
        await sec_register(g, entry.user.id, "kick", f"👢 {member} (`{member.id}`) ی Kick کرد")


async def sec_on_member_join(member):
    if not member.bot:
        return
    g = member.guild
    if not sec_mod_on(g, "bot_add"):
        return
    entry = await sec_audit(g, [discord.AuditLogAction.bot_add], member.id)
    if not (entry and entry.user) or sec_exempt(g, entry.user.id):
        return
    try:
        await member.kick(reason="Security: Anti-Bot Add")
    except Exception:
        pass
    await sec_register(g, entry.user.id, "bot_add", f"🤖 بۆتی {member} (`{member.id}`) ی زیادکرد (دەرکرا)")


bot.add_listener(sec_on_message, "on_message")
bot.add_listener(sec_on_channel_create, "on_guild_channel_create")
bot.add_listener(sec_on_channel_delete, "on_guild_channel_delete")
bot.add_listener(sec_on_channel_update, "on_guild_channel_update")
bot.add_listener(sec_on_role_create, "on_guild_role_create")
bot.add_listener(sec_on_role_delete, "on_guild_role_delete")
bot.add_listener(sec_on_role_update, "on_guild_role_update")
bot.add_listener(sec_on_ban, "on_member_ban")
bot.add_listener(sec_on_member_remove, "on_member_remove")
bot.add_listener(sec_on_member_join, "on_member_join")


# ---------------------------------------------------------
# /security panel
# ---------------------------------------------------------

def sec_main_embed(guild):
    s = get_sec(guild.id)
    lines = []
    for k, (label, *_rest) in SEC_MODULES.items():
        m = s["modules"][k]
        lines.append(
            f"{'🟢' if m['enabled'] else '🔴'} **{label}** — `{m['limit']}` / `{m['seconds']}s` / `{m['timeout']}m`"
            + (" 🎭" if m["remove_roles"] else "")
        )
    e = discord.Embed(
        title="🛡️ Security " + ("(ON)" if s["enabled"] else "(OFF)"),
        description="\n".join(lines),
        color=discord.Color.green() if s["enabled"] else discord.Color.red()
    )
    lc = s.get("log_channel")
    e.add_field(
        name="کەناڵی وارنینگ",
        value=f"<#{lc}>" if lc else "❌ دیاری نەکراوە (Server Log بەکاردێت)",
        inline=False
    )
    e.add_field(
        name="سزا",
        value=f"**{SEC_PUNISH_LABELS[s['punish']]}**\n🎭 = ڕۆڵەکان لادەبرێن",
        inline=False
    )
    e.set_footer(text="Limit / Seconds / Timeout(خولەک) — بەشێک هەڵبژێرە بۆ دەستکاری")
    return e


def sec_module_embed(guild, key):
    label, _, _, _, _, hint = SEC_MODULES[key]
    m = get_sec(guild.id)["modules"][key]
    e = discord.Embed(
        title=f"🛡️ {label}",
        description=hint,
        color=discord.Color.green() if m["enabled"] else discord.Color.red()
    )
    e.add_field(name="Status", value="🟢 ON" if m["enabled"] else "🔴 OFF")
    e.add_field(name="Limit", value=f"`{m['limit']}`")
    e.add_field(name="Seconds", value=f"`{m['seconds']}`")
    e.add_field(name="Timeout (خولەک)", value=f"`{m['timeout']}`")
    e.add_field(name="Remove Roles", value="🎭 بەڵێ" if m["remove_roles"] else "نەخێر")
    return e


def sec_wl_embed(guild):
    s = get_sec(guild.id)
    us = ", ".join(f"<@{u}>" for u in s["wl_users"]) or "—"
    rs = ", ".join(f"<@&{r}>" for r in s["wl_roles"]) or "—"
    return discord.Embed(
        title="✅ Whitelist",
        description=(
            f"**Users:** {us}\n**Roles:** {rs}\n\n"
            "ئەوەی هەڵیدەبژێریت: ئەگەر لە لیستدا بێت لادەچێت، ئەگەر نەبێت زیاد دەبێت.\n"
            "Owner و Developer (`/setdev`) خۆکار ڕزگاربوون."
        ),
        color=discord.Color.blurple()
    )


class SecBaseView(discord.ui.View):
    def __init__(self, guild, author_id):
        super().__init__(timeout=300)
        self.guild = guild
        self.author_id = author_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id or not is_dev(interaction.user):
            await deny_interaction(interaction)
            return False
        return True


class SecModuleSelect(discord.ui.Select):
    def __init__(self, guild):
        s = get_sec(guild.id)
        opts = [
            discord.SelectOption(
                label=label, value=k, description=hint[:100],
                emoji="🟢" if s["modules"][k]["enabled"] else "🔴"
            )
            for k, (label, _, _, _, _, hint) in SEC_MODULES.items()
        ]
        super().__init__(placeholder="بەشێک هەڵبژێرە...", options=opts, row=0)

    async def callback(self, interaction):
        key = self.values[0]
        await interaction.response.edit_message(
            embed=sec_module_embed(self.view.guild, key),
            view=SecModuleView(self.view.guild, self.view.author_id, key)
        )


class SecLogChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="کەناڵی وارنینگ هەڵبژێرە...",
            channel_types=[discord.ChannelType.text],
            min_values=1, max_values=1, row=1
        )

    async def callback(self, interaction):
        get_sec(self.view.guild.id)["log_channel"] = self.values[0].id
        save_config()
        await interaction.response.edit_message(
            embed=sec_main_embed(self.view.guild),
            view=SecMainView(self.view.guild, self.view.author_id)
        )


class SecMainView(SecBaseView):
    def __init__(self, guild, author_id):
        super().__init__(guild, author_id)
        s = get_sec(guild.id)
        self.add_item(SecModuleSelect(guild))
        self.add_item(SecLogChannelSelect())
        self.toggle.label = "Security: ON" if s["enabled"] else "Security: OFF"
        self.toggle.style = discord.ButtonStyle.success if s["enabled"] else discord.ButtonStyle.danger
        self.punish_btn.label = "Punishment: " + SEC_PUNISH_LABELS[s["punish"]]

    @discord.ui.button(label="Security", row=2)
    async def toggle(self, interaction, button):
        s = get_sec(self.guild.id)
        s["enabled"] = not s["enabled"]
        save_config()
        await interaction.response.edit_message(
            embed=sec_main_embed(self.guild), view=SecMainView(self.guild, self.author_id))

    @discord.ui.button(label="Punishment", style=discord.ButtonStyle.primary, row=2)
    async def punish_btn(self, interaction, button):
        s = get_sec(self.guild.id)
        i = SEC_PUNISH_ORDER.index(s["punish"])
        s["punish"] = SEC_PUNISH_ORDER[(i + 1) % len(SEC_PUNISH_ORDER)]
        save_config()
        await interaction.response.edit_message(
            embed=sec_main_embed(self.guild), view=SecMainView(self.guild, self.author_id))

    @discord.ui.button(label="Whitelist", style=discord.ButtonStyle.secondary, row=3)
    async def wl_btn(self, interaction, button):
        await interaction.response.edit_message(
            embed=sec_wl_embed(self.guild), view=SecWhitelistView(self.guild, self.author_id))


class SecLimitModal(discord.ui.Modal):
    def __init__(self, guild, author_id, key):
        super().__init__(title=f"Edit: {SEC_MODULES[key][0]}"[:45])
        m = get_sec(guild.id)["modules"][key]
        self.guild, self.author_id, self.key = guild, author_id, key
        self.limit = discord.ui.TextInput(label="Limit", default=str(m["limit"]), max_length=4)
        self.seconds = discord.ui.TextInput(label="Seconds (چرکە)", default=str(m["seconds"]), max_length=5)
        self.timeout_min = discord.ui.TextInput(label="Timeout (خولەک)", default=str(m["timeout"]), max_length=5)
        self.add_item(self.limit)
        self.add_item(self.seconds)
        self.add_item(self.timeout_min)

    async def on_submit(self, interaction):
        try:
            lim = int(self.limit.value)
            sec = int(self.seconds.value)
            tmo = int(self.timeout_min.value)
            assert lim >= 0 and sec >= 0 and 1 <= tmo <= 40320
        except Exception:
            await interaction.response.send_message(
                "❌ تەنها ژمارە بنووسە (Timeout لە 1 تا 40320 خولەک).", ephemeral=True)
            return
        m = get_sec(self.guild.id)["modules"][self.key]
        m["limit"], m["seconds"], m["timeout"] = lim, sec, tmo
        save_config()
        await interaction.response.edit_message(
            embed=sec_module_embed(self.guild, self.key),
            view=SecModuleView(self.guild, self.author_id, self.key))


class SecModuleView(SecBaseView):
    def __init__(self, guild, author_id, key):
        super().__init__(guild, author_id)
        self.key = key
        mm = get_sec(guild.id)["modules"][key]
        on = mm["enabled"]
        self.toggle.label = "Turn OFF" if on else "Turn ON"
        self.toggle.style = discord.ButtonStyle.danger if on else discord.ButtonStyle.success
        self.roles_btn.label = "Remove Roles: " + ("ON" if mm["remove_roles"] else "OFF")
        self.roles_btn.style = discord.ButtonStyle.success if mm["remove_roles"] else discord.ButtonStyle.secondary

    @discord.ui.button(label="Toggle")
    async def toggle(self, interaction, button):
        m = get_sec(self.guild.id)["modules"][self.key]
        m["enabled"] = not m["enabled"]
        save_config()
        await interaction.response.edit_message(
            embed=sec_module_embed(self.guild, self.key),
            view=SecModuleView(self.guild, self.author_id, self.key))

    @discord.ui.button(label="Remove Roles", row=1)
    async def roles_btn(self, interaction, button):
        m = get_sec(self.guild.id)["modules"][self.key]
        m["remove_roles"] = not m["remove_roles"]
        save_config()
        await interaction.response.edit_message(
            embed=sec_module_embed(self.guild, self.key),
            view=SecModuleView(self.guild, self.author_id, self.key))

    @discord.ui.button(label="Edit Limit / Seconds / Timeout", style=discord.ButtonStyle.primary)
    async def edit_btn(self, interaction, button):
        await interaction.response.send_modal(SecLimitModal(self.guild, self.author_id, self.key))

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back(self, interaction, button):
        await interaction.response.edit_message(
            embed=sec_main_embed(self.guild), view=SecMainView(self.guild, self.author_id))


class SecWLUsers(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="Users", min_values=1, max_values=10, row=0)

    async def callback(self, interaction):
        s = get_sec(self.view.guild.id)
        for u in self.values:
            if u.id in s["wl_users"]:
                s["wl_users"].remove(u.id)
            else:
                s["wl_users"].append(u.id)
        save_config()
        await interaction.response.edit_message(
            embed=sec_wl_embed(self.view.guild),
            view=SecWhitelistView(self.view.guild, self.view.author_id))


class SecWLRoles(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="Roles", min_values=1, max_values=10, row=1)

    async def callback(self, interaction):
        s = get_sec(self.view.guild.id)
        for r in self.values:
            if r.id in s["wl_roles"]:
                s["wl_roles"].remove(r.id)
            else:
                s["wl_roles"].append(r.id)
        save_config()
        await interaction.response.edit_message(
            embed=sec_wl_embed(self.view.guild),
            view=SecWhitelistView(self.view.guild, self.view.author_id))


class SecWhitelistView(SecBaseView):
    def __init__(self, guild, author_id):
        super().__init__(guild, author_id)
        self.add_item(SecWLUsers())
        self.add_item(SecWLRoles())

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction, button):
        await interaction.response.edit_message(
            embed=sec_main_embed(self.guild), view=SecMainView(self.guild, self.author_id))


@bot.tree.command(name="security", description="سیستمی پاراستن (Anti-Spam / Anti-Nuke)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
async def security_cmd(interaction: discord.Interaction):
    if not is_dev(interaction.user):
        await deny_interaction(interaction)
        return
    await interaction.response.send_message(
        embed=sec_main_embed(interaction.guild),
        view=SecMainView(interaction.guild, interaction.user.id),
        ephemeral=True
    )


# =========================================================
# 29.5 DOMINO GAME  (/domino)
# =========================================================
# Double-six dominoes, 2-4 players, 7 tiles each, draw from the boneyard.
# Players use the "My Hand" button (private message) to play / draw / pass.

# ---- DOMINO-LOGIC-START ----
class DominoGame:
    MAX_PLAYERS = 4
    HAND_SIZE = 7

    def __init__(self, channel, host_id):
        self.channel = channel
        self.host_id = host_id
        self.players = [host_id]
        self.hands = {}
        self.board = []          # list of (left, right) tiles in chain order
        self.boneyard = []
        self.turn = 0
        self.passes = 0
        self.started = False
        self.finished = False
        self.result = ""
        self.last = ""
        self.message = None      # public game message
        self.lock = asyncio.Lock()

    # ---------- helpers ----------
    def ends(self):
        if not self.board:
            return None, None
        return self.board[0][0], self.board[-1][1]

    def current(self):
        return self.players[self.turn]

    def playable_sides(self, tile):
        """['R'] / ['L'] / ['R','L'] - which chain ends this tile fits."""
        if not self.board:
            return ["R"]
        left, right = self.ends()
        sides = []
        if right in tile:
            sides.append("R")
        if left in tile and left != right:
            sides.append("L")
        return sides

    def playable_tiles(self, uid):
        return [t for t in self.hands[uid] if self.playable_sides(t)]

    def pips(self, uid):
        return sum(a + b for a, b in self.hands[uid])

    # ---------- start ----------
    def deal(self):
        tiles = [(i, j) for i in range(7) for j in range(i, 7)]
        random.shuffle(tiles)
        for uid in self.players:
            self.hands[uid] = sorted(tiles.pop() for _ in range(self.HAND_SIZE))
        self.boneyard = tiles
        self.started = True

        # the player with the highest double (else highest tile) opens
        best = None
        for idx, uid in enumerate(self.players):
            for t in self.hands[uid]:
                key = (1 if t[0] == t[1] else 0, t[0] + t[1], max(t))
                if best is None or key > best[0]:
                    best = (key, idx, uid, t)
        _, idx, uid, tile = best
        self.hands[uid].remove(tile)
        self.board.append(tile)
        self.last = f"🎯 <@{uid}> یاری دەستپێکرد بە `[{tile[0]}|{tile[1]}]`"
        self.turn = (idx + 1) % len(self.players)

    # ---------- moves ----------
    def _advance(self):
        self.turn = (self.turn + 1) % len(self.players)

    def play(self, uid, tile, side):
        """Returns an error text, or None if the move was made."""
        if self.finished:
            return "یاریەکە تەواو بووە."
        if self.current() != uid:
            return "نۆرەی تۆ نییە."
        if tile not in self.hands[uid]:
            return "ئەم تایڵە لە دەستتدا نییە."
        if side not in self.playable_sides(tile):
            return "ئەم تایڵە لەم لایەدا ناگونجێت."

        left, right = self.ends()
        if side == "R":
            oriented = tile if tile[0] == right else (tile[1], tile[0])
            self.board.append(oriented)
        else:
            oriented = tile if tile[1] == left else (tile[1], tile[0])
            self.board.insert(0, oriented)

        self.hands[uid].remove(tile)
        self.passes = 0
        self.last = f"✅ <@{uid}> `[{oriented[0]}|{oriented[1]}]` ی دانا"

        if not self.hands[uid]:
            self.finished = True
            others = sum(self.pips(u) for u in self.players if u != uid)
            self.result = f"🏆 <@{uid}> براوەیە! (+{others} خاڵ)"
        else:
            self._advance()
        return None

    def draw(self, uid):
        """Returns (tile, error)."""
        if self.finished:
            return None, "یاریەکە تەواو بووە."
        if self.current() != uid:
            return None, "نۆرەی تۆ نییە."
        if self.playable_tiles(uid):
            return None, "تایڵی گونجاوت هەیە، دەبێت یاری بکەیت."
        if not self.boneyard:
            return None, "تایڵی ماوە نەماوە، Pass بکە."
        tile = self.boneyard.pop()
        self.hands[uid] = sorted(self.hands[uid] + [tile])
        self.last = f"🎴 <@{uid}> تایڵێکی هەڵگرت"
        return tile, None

    def pass_turn(self, uid):
        if self.finished:
            return "یاریەکە تەواو بووە."
        if self.current() != uid:
            return "نۆرەی تۆ نییە."
        if self.playable_tiles(uid) or self.boneyard:
            return "ناتوانیت Pass بکەیت."
        self.passes += 1
        self.last = f"⏭️ <@{uid}> Pass ی کرد"
        if self.passes >= len(self.players):
            self._finish_blocked()
        else:
            self._advance()
        return None

    def _finish_blocked(self):
        self.finished = True
        totals = {u: self.pips(u) for u in self.players}
        low = min(totals.values())
        winners = [u for u, v in totals.items() if v == low]
        detail = " | ".join(f"<@{u}>: {v}" for u, v in totals.items())
        if len(winners) == 1:
            self.result = f"🔒 یاری گیرا! کەمترین خاڵ: <@{winners[0]}> براوەیە\n{detail}"
        else:
            self.result = f"🔒 یاری گیرا و یەکسان بوون\n{detail}"
# ---- DOMINO-LOGIC-END ----


_domino_games = {}   # channel_id -> DominoGame


def domino_tile_text(tile):
    return f"[{tile[0]}|{tile[1]}]"


def domino_board_text(game):
    if not game.board:
        return "—"
    tiles = [domino_tile_text(t) for t in game.board]
    rows = [" ".join(tiles[i:i + 5]) for i in range(0, len(tiles), 5)]
    return "\n".join(rows)


def domino_embed(game):
    left, right = game.ends()
    e = discord.Embed(
        title="🁣 Domino",
        color=discord.Color.gold() if game.finished else discord.Color.blurple()
    )
    e.add_field(
        name=f"مێز  (⬅️ {left}   {right} ➡️)" if left is not None else "مێز",
        value=f"```\n{domino_board_text(game)}\n```",
        inline=False
    )

    lines = []
    for i, uid in enumerate(game.players):
        mark = "▶️" if (not game.finished and i == game.turn) else "▫️"
        lines.append(f"{mark} <@{uid}> — `{len(game.hands[uid])}` تایڵ")
    lines.append(f"\n📦 تایڵی ماوە: `{len(game.boneyard)}`")
    e.add_field(name="یاریزانان", value="\n".join(lines), inline=False)

    if game.last:
        e.add_field(name="دوایین کار", value=game.last, inline=False)

    if game.finished:
        left_over = "\n".join(
            f"<@{u}>: " + (" ".join(domino_tile_text(t) for t in game.hands[u]) or "—")
            for u in game.players
        )
        e.add_field(name="ئەنجام", value=game.result, inline=False)
        e.add_field(name="تایڵەکانی ماوە", value=left_over, inline=False)
    else:
        e.set_footer(text="دوگمەی «My Hand» دابگرە بۆ بینینی تایڵەکانت")
    return e


async def domino_refresh(game):
    """Update the public game message."""
    try:
        if game.message is None:
            return
        await game.message.edit(
            embed=domino_embed(game),
            view=None if game.finished else DominoGameView(game),
            allowed_mentions=discord.AllowedMentions.none()
        )
    except Exception as e:
        print(f"domino_refresh error: {e}")
    if game.finished:
        domino_cleanup(game)


def domino_cleanup(game):
    if _domino_games.get(game.channel.id) is game:
        _domino_games.pop(game.channel.id, None)


def domino_hand_text(game, uid, note=""):
    hand = game.hands.get(uid, [])
    tiles = " ".join(domino_tile_text(t) for t in hand) or "—"
    left, right = game.ends()
    ends = f"⬅️ `{left}`   `{right}` ➡️" if left is not None else ""
    if game.finished:
        status = game.result
    elif game.current() == uid:
        playable = game.playable_tiles(uid)
        if playable:
            status = "🟢 نۆرەی تۆیە، تایڵێک هەڵبژێرە."
        elif game.boneyard:
            status = "🟡 تایڵی گونجاوت نییە، **Draw** بکە."
        else:
            status = "🟠 تایڵی گونجاوت نییە و تایڵی ماوە نەماوە، **Pass** بکە."
    else:
        status = f"⏳ چاوەڕێی <@{game.current()}> بکە."
    parts = [p for p in (note, f"**تایڵەکانت:**\n```\n{tiles}\n```", ends, status) if p]
    return "\n".join(parts)


def domino_parse_tile(value):
    a, b = value.split("-")
    return tuple(sorted((int(a), int(b))))


async def domino_do_move(interaction, game, uid, tile, side):
    async with game.lock:
        err = game.play(uid, tile, side)
    if err:
        await interaction.response.edit_message(
            content=f"❌ {err}", view=DominoHandView(game, uid))
        return
    await interaction.response.edit_message(
        content=domino_hand_text(game, uid, f"✅ `{domino_tile_text(tile)}` دانرا"),
        view=DominoHandView(game, uid),
        allowed_mentions=discord.AllowedMentions.none()
    )
    await domino_refresh(game)


class DominoTileSelect(discord.ui.Select):
    def __init__(self, game, uid, tiles):
        opts = []
        for t in tiles[:25]:
            sides = game.playable_sides(t)
            where = "/".join("ڕاست" if s == "R" else "چەپ" for s in sides)
            opts.append(discord.SelectOption(
                label=domino_tile_text(t), value=f"{t[0]}-{t[1]}", description=where))
        super().__init__(placeholder="تایڵێک هەڵبژێرە...", options=opts)
        self.game = game
        self.uid = uid

    async def callback(self, interaction):
        game, uid = self.game, self.uid
        tile = domino_parse_tile(self.values[0])
        sides = game.playable_sides(tile)
        if len(sides) == 2:
            await interaction.response.edit_message(
                content=f"`{domino_tile_text(tile)}` لە کام لا دایبنێم؟",
                view=DominoSideView(game, uid, tile)
            )
        elif sides:
            await domino_do_move(interaction, game, uid, tile, sides[0])
        else:
            await interaction.response.edit_message(
                content="❌ ئەم تایڵە ناگونجێت.", view=DominoHandView(game, uid))


class DominoDrawButton(discord.ui.Button):
    def __init__(self, game, uid):
        super().__init__(label="Draw (هەڵگرتنی تایڵ)", style=discord.ButtonStyle.primary, emoji="🎴")
        self.game = game
        self.uid = uid

    async def callback(self, interaction):
        game, uid = self.game, self.uid
        async with game.lock:
            tile, err = game.draw(uid)
        if err:
            await interaction.response.edit_message(
                content=f"❌ {err}", view=DominoHandView(game, uid))
            return
        await interaction.response.edit_message(
            content=domino_hand_text(game, uid, f"🎴 تایڵی `{domino_tile_text(tile)}` ت هەڵگرت"),
            view=DominoHandView(game, uid),
            allowed_mentions=discord.AllowedMentions.none()
        )
        await domino_refresh(game)


class DominoPassButton(discord.ui.Button):
    def __init__(self, game, uid):
        super().__init__(label="Pass", style=discord.ButtonStyle.secondary, emoji="⏭️")
        self.game = game
        self.uid = uid

    async def callback(self, interaction):
        game, uid = self.game, self.uid
        async with game.lock:
            err = game.pass_turn(uid)
        if err:
            await interaction.response.edit_message(
                content=f"❌ {err}", view=DominoHandView(game, uid))
            return
        await interaction.response.edit_message(
            content=domino_hand_text(game, uid, "⏭️ Pass ت کرد"),
            view=DominoHandView(game, uid),
            allowed_mentions=discord.AllowedMentions.none()
        )
        await domino_refresh(game)


class DominoHandView(discord.ui.View):
    """Private (ephemeral) hand of one player."""
    def __init__(self, game, uid):
        super().__init__(timeout=600)
        if game.finished or game.current() != uid:
   
