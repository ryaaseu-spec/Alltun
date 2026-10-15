import discord
from discord import app_commands
from discord.ext import commands
import datetime
import os
import json
import asyncio

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
}

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
    d.setdefault("welcome_text", "Baxer beyt")
    d.setdefault("welcome_image", None)  # image / gif link shown under the welcome text
    d.setdefault("dev_roles", [])      # developer roles (full control like owner)
    d.setdefault("mute_role", None)    # role given on mute (set with /setmuterole)
    perm = d.setdefault("perm_roles", {})  # roles allowed: mute / ban / safika
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


def get_mute_role(guild):
    """Role chosen with /setmuterole, otherwise a role named Muted"""
    rid = cfg(guild.id).get("mute_role")
    if rid:
        role = guild.get_role(rid)
        if role:
            return role
    return get_mute_role(guild)


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


# =========================================================
# 5. READY
# =========================================================

@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
    except Exception:
        pass

    for guild in bot.guilds:
        try:
            mute_role = get_mute_role(guild)
            if mute_role:
                await sync_muted_permissions(guild, mute_role)
        except Exception:
            pass

    print(f"بۆتەکە بە سەرکەوتوویی چالاک بوو وەک: {bot.user}")
    print(f"Config file: {CONFIG_FILE}")


# =========================================================
# 6. WELCOME
# =========================================================

@bot.event
async def on_member_join(member):
    c = cfg(member.guild.id)
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
        entry = await get_audit_executor(after.guild, discord.AuditLogAction.role_update, after.id)
        embed = make_embed(
            "✏️ Role Updated",
            f"**Role:** {after.mention}\n"
            f"**ID:** `{after.id}`\n"
            f"**Updated By:** {who(entry)}\n\n"
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
    entry = await get_audit_executor(guild, discord.AuditLogAction.ban, user.id)
    embed = make_embed(
        "🔨 Member Banned",
        f"**Member:** {user.mention}\n**Banned By:** {who(entry)}",
        discord.Color.red()
    )
    add_user_thumbnail(embed, user)
    await send_log(guild, "ban", embed)


@bot.event
async def on_member_unban(guild, user):
    entry = await get_audit_executor(guild, discord.AuditLogAction.unban, user.id)
    embed = make_embed(
        "♻ Member Unbanned",
        f"**Member:** {user.mention}\n**Unbanned By:** {who(entry)}",
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
    if command == "safika":
        if not has_cmd_access(message.author, "safika"):
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
                await target.add_roles(muted_role, reason=f"Muted by {message.author}")
            try:
                await message.delete()
            except Exception:
                pass
            await message.channel.send(f"damt daxaa {target.mention}", delete_after=2)
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
                await target.remove_roles(muted_role)
            try:
                await message.delete()
            except Exception:
                pass
            await message.channel.send(
                f"xwa xerm bnwse dllm basha aqllba amjara {target.mention}",
                delete_after=2
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
            await target.ban(reason=f"Banned by {message.author}")
            try:
                await message.delete()
            except Exception:
                pass
            await message.channel.send(f"Frenraa✈️ {target.mention}", delete_after=2)
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
            await message.guild.unban(user)
            try:
                await message.delete()
            except Exception:
                pass
            await message.channel.send("✅ Unban کرا.", delete_after=3)
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
            try:
                await message.delete()
            except Exception:
                pass
            await message.channel.send("🔒 کەناڵەکە Lock کرا.", delete_after=3)
        except Exception:
            pass
        return

    # ---------------- UNLOCK ----------------
    if command == "unlock":
        if not message.author.guild_permissions.manage_channels:
            return
        try:
            await message.channel.set_permissions(message.guild.default_role, send_messages=None)
            try:
                await message.delete()
            except Exception:
                pass
            await message.channel.send("🔓 کەناڵەکە Unlock کرا.", delete_after=3)
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
        await interaction.response.send_message("❌ تەنها خاوەنی سێرڤەر و ڕۆڵی دیڤیلۆپەر.", ephemeral=True)
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
        await interaction.response.send_message("❌ تەنها خاوەنی سێرڤەر و ڕۆڵی دیڤیلۆپەر.", ephemeral=True)
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
        await interaction.response.send_message("❌ تەنها خاوەنی سێرڤەر و ڕۆڵی دیڤیلۆپەر.", ephemeral=True)
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
@app_commands.describe(slot="ژمارەی ڕۆڵ", role="ڕۆڵەکە")
@app_commands.choices(
    slot=[
        app_commands.Choice(name="Staff Role 1", value="staff1"),
        app_commands.Choice(name="Staff Role 2", value="staff2"),
    ]
)
async def setstaff(interaction: discord.Interaction, slot: str, role: discord.Role):
    if not is_dev(interaction.user):
        await interaction.response.send_message("❌ تەنها خاوەنی سێرڤەر و ڕۆڵی دیڤیلۆپەر.", ephemeral=True)
        return

    cfg(interaction.guild.id)["roles"][slot] = role.id
    save_config()

    await interaction.response.send_message(
        f"✅ {slot} → **{role.name}**", ephemeral=True
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
        await interaction.response.send_message("❌ تەنها خاوەنی سێرڤەر و ڕۆڵی دیڤیلۆپەر.", ephemeral=True)
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
    await interaction.response.send_message(msg, ephemeral=True)


# ---------------------------------------------------------
# /rolemute  /roleban  /rolesafika
# ---------------------------------------------------------

async def update_perm_role(interaction, key, action, role):
    user = interaction.user
    if not is_dev(user):
        await interaction.response.send_message(
            "❌ تەنها خاوەنی سێرڤەر و ڕۆڵی دیڤیلۆپەر.", ephemeral=True
        )
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


@bot.tree.command(name="setmuterole", description="دیاریکردنی ئەو ڕۆڵەی لە کاتی Mute دەدرێت بە کەسەکە")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@app_commands.describe(role="ڕۆڵی Mute (بۆ نموونە Muted)")
async def setmuterole(interaction: discord.Interaction, role: discord.Role):
    if not is_dev(interaction.user):
        await interaction.response.send_message(
            "❌ تەنها خاوەنی سێرڤەر و ڕۆڵی دیڤیلۆپەر.", ephemeral=True
        )
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


@bot.tree.command(name="setdev", description="دیاریکردنی ڕۆڵی دیڤیلۆپەر (تەنها خاوەنی سێرڤەر)")
@app_commands.guild_only()
@app_commands.describe(action="زیادکردن یان لابردن", role="ڕۆڵی دیڤیلۆپەر")
@app_commands.choices(action=PERM_ACTION_CHOICES)
async def setdev(interaction: discord.Interaction, action: str, role: discord.Role):
    if interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message(
            "❌ تەنها خاوەنی سێرڤەر دەتوانێت ڕۆڵی دیڤیلۆپەر دیاری بکات.", ephemeral=True
        )
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
        await interaction.response.send_message("❌ تەنها خاوەنی سێرڤەر و ڕۆڵی دیڤیلۆپەر.", ephemeral=True)
        return

    c = cfg(interaction.guild.id)
    lines = []

    for k, name in LOG_TYPES.items():
        cid = c["channels"].get(k)
        lines.append(f"**{name}:** {f'<#{cid}>' if cid else '❌'}")

    for slot in ("staff1", "staff2"):
        rid = c["roles"].get(slot)
        lines.append(f"**{slot}:** {f'<@&{rid}>' if rid else '❌'}")

    regri = ", ".join(f"<@&{r}>" for r in c["regri_roles"]) or "❌"
    lines.append(f"**Regri roles:** {regri}")

    dev = ", ".join(f"<@&{r}>" for r in c["dev_roles"]) or "❌ (تەنها Owner)"
    lines.append(f"**Developer roles:** {dev}")

    mrid = c.get("mute_role")
    lines.append(f"**Mute role:** {f'<@&{mrid}>' if mrid else '❌ (Muted بە ناو)'}")

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
        app_commands.Choice(name="Staff Role 1", value="staff1"),
        app_commands.Choice(name="Staff Role 2", value="staff2"),
    ]
)
async def staff(
    interaction: discord.Interaction,
    member: discord.Member,
    role_choice: str
):
    if not is_dev(interaction.user):
        await interaction.response.send_message(
            "❌ تەنها خاوەنی سێرڤەر و ڕۆڵی دیڤیلۆپەر دەتوانێت ئەم کۆماندە بەکاربهێنێت.", ephemeral=True
        )
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

@bot.tree.command(name="rangi-role", description="گۆڕینی ڕەنگی ڕۆڵ")
@app_commands.guild_only()
@app_commands.describe(
    role="ناوی ڕۆڵەکە بنووسە یان هەڵبژێرە",
    color="کۆدی ڕەنگ بۆ نموونە #FF0000"
)
async def rangi_role(interaction: discord.Interaction, role: str, color: str):
    if not is_dev(interaction.user):
        await interaction.response.send_message(
            "❌ تەنها خاوەنی سێرڤەر و ڕۆڵی دیڤیلۆپەر دەتوانێت ئەم کۆماندە بەکاربهێنێت.", ephemeral=True
        )
        return

    guild = interaction.guild

    if interaction.user.id in cfg(guild.id)["restricted"]:
        await interaction.response.send_message(
            "❌ تۆ قەدەغەکراوی لە گۆڕینی ڕەنگ!", ephemeral=True
        )
        return

    if role.isdigit():
        target_role = guild.get_role(int(role))
    else:
        target_role = discord.utils.get(guild.roles, name=role)

    if not target_role:
        await interaction.response.send_message("❌ ڕۆڵەکە نەدۆزرایەوە!", ephemeral=True)
        return

    user_top_role = interaction.user.top_role
    is_owner = interaction.user.id == guild.owner_id

    if (
        target_role.name == "@everyone"
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

    try:
        color_obj = discord.Color(int(color.strip().lstrip("#"), 16))
        await target_role.edit(color=color_obj)
        await interaction.response.send_message(
            f"✅ ڕەنگی ڕۆڵی **{target_role.name}** بە سەرکەوتوویی گۆڕدرا!",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(
            f"❌ هەڵە لە نووسینی کۆدی ڕەنگەکەدا هەیە: {e}", ephemeral=True
        )


@rangi_role.autocomplete("role")
async def rangi_role_autocomplete(interaction: discord.Interaction, current: str):
    guild = interaction.guild
    if not guild:
        return []

    user_top_role = interaction.user.top_role
    is_owner = interaction.user.id == guild.owner_id
    options = []

    for r in guild.roles:
        if r.name == "@everyone" or r.managed or r.is_bot_managed():
            continue
        if not is_owner and r > user_top_role:
            continue
        if current.lower() in r.name.lower():
            options.append(app_commands.Choice(name=r.name, value=str(r.id)))
            if len(options) >= 25:
                break

    return options


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
        await interaction.response.send_message(
            "❌ تەنها ڕۆڵە دیاریکراوەکان و خاوەنی سێرڤەر دەتوانن ئەم کۆماندە بەکاربهێنن.",
            ephemeral=True
        )
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
# 29. RUN BOT
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")

if TOKEN:
    bot.run(TOKEN)
