"""
music.py  —  /gorani  (Music player for the Karezma bot)

بۆتەکە دێتە ڤۆیس، گۆرانی ئەژەنێت و پانێڵی جوانی لە چات دائەنێت
(پاوس / پێشوو / دواتر / لووپ / ستۆپ / دەنگ / تێکەڵکردن / لیست).

خۆکار لەلایەن bot.py ەوە بار دەکرێت (load_extension).
"""

import asyncio
import os
import random
import shutil
import tempfile
import time
import traceback
from collections import deque
from dataclasses import dataclass
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

try:
    import yt_dlp
except ImportError:  # requirements.txt must contain yt-dlp
    yt_dlp = None

# ---------------------------------------------------------
# Style  (soft pink / lilac glass look)
# ---------------------------------------------------------
PINK = 0xF6C1D9
LILAC = 0xDCCBF7
LOOP_NAMES = ["Off", "Track", "Queue"]
IDLE_TIMEOUT = 180          # seconds to wait for a new song before leaving
ALONE_TICKS = 6             # x10s alone in voice -> leave
MAX_VOLUME = 1.5
FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def fmt_time(seconds):
    seconds = int(max(0, seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def make_bar(elapsed, total, size=14):
    if total <= 0:
        return "━" * size
    pos = min(size - 1, int(elapsed / total * size))
    return "━" * pos + "●" + "─" * (size - 1 - pos)


def clean_title(text, limit=75):
    text = (text or "Unknown").replace("[", "(").replace("]", ")")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _cookie_file():
    """Optional YouTube cookies (Railway Variables: YT_COOKIES or YT_COOKIES_FILE)."""
    path = os.getenv("YT_COOKIES_FILE")
    if path and os.path.exists(path):
        return path
    raw = os.getenv("YT_COOKIES")
    if raw:
        target = os.path.join(tempfile.gettempdir(), "yt_cookies.txt")
        with open(target, "w", encoding="utf-8") as f:
            f.write(raw.replace("\\n", "\n"))
        return target
    return None


def _ytdl_options():
    opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "source_address": "0.0.0.0",
        "socket_timeout": 20,
    }
    cookies = _cookie_file()
    if cookies:
        opts["cookiefile"] = cookies
    return opts


def _extract(query):
    """Blocking yt-dlp call (run it with asyncio.to_thread)."""
    target = query if query.startswith(("http://", "https://")) else f"ytsearch1:{query}"
    with yt_dlp.YoutubeDL(_ytdl_options()) as ydl:
        info = ydl.extract_info(target, download=False)
    if info is None:
        raise RuntimeError("no result")
    if "entries" in info:
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise RuntimeError("no result")
        info = entries[0]
    if not info.get("url"):
        raise RuntimeError("no stream url")
    return info


def _ensure_opus():
    if discord.opus.is_loaded():
        return
    for name in ("opus", "libopus.so.0", "libopus.so", "libopus-0.dll"):
        try:
            discord.opus.load_opus(name)
            if discord.opus.is_loaded():
                return
        except Exception:
            continue


@dataclass
class Track:
    title: str
    page_url: str
    duration: int
    thumbnail: Optional[str]
    uploader: str
    requester: str
    stream_url: Optional[str] = None
    resolved_at: float = 0.0


def info_to_track(info, requester):
    return Track(
        title=info.get("title") or "Unknown",
        page_url=info.get("webpage_url") or info.get("original_url") or info.get("url"),
        duration=int(info.get("duration") or 0),
        thumbnail=info.get("thumbnail"),
        uploader=info.get("uploader") or info.get("channel") or "",
        requester=requester,
        stream_url=info.get("url"),
        resolved_at=time.time(),
    )


# ---------------------------------------------------------
# Player panel (buttons)
# ---------------------------------------------------------
class PlayerView(discord.ui.View):
    def __init__(self, player):
        super().__init__(timeout=None)
        self.player = player
        self.refresh()

    def refresh(self):
        p = self.player
        vc = p.vc
        paused = bool(vc and vc.is_paused())
        self.btn_pause.emoji = "▶️" if paused else "⏸️"
        self.btn_loop.emoji = "🔂" if p.loop_mode == 1 else "🔁"
        self.btn_loop.style = (
            discord.ButtonStyle.primary if p.loop_mode else discord.ButtonStyle.secondary
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        vc = self.player.vc
        user = interaction.user
        ok = (
            isinstance(user, discord.Member)
            and user.voice is not None
            and user.voice.channel is not None
            and vc is not None
            and vc.channel is not None
            and user.voice.channel.id == vc.channel.id
        )
        if not ok:
            await interaction.response.send_message(
                "پێویستە لەگەڵ بۆتەکە لە هەمان ڤۆیس بیت ♡", ephemeral=True
            )
        return ok

    # ---- row 0 ----
    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        p = self.player
        await interaction.response.defer()
        if p.vc and p.current:
            p.action = "prev"
            p.vc.stop()

    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        p = self.player
        vc = p.vc
        if vc is None or p.current is None:
            await interaction.response.defer()
            return
        if vc.is_paused():
            vc.resume()
            p.mark_resumed()
        elif vc.is_playing():
            vc.pause()
            p.mark_paused()
        self.refresh()
        await interaction.response.edit_message(embed=p.build_embed(), view=self)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        p = self.player
        await interaction.response.defer()
        if p.vc and p.current:
            p.action = "skip"
            p.vc.stop()

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, row=0)
    async def btn_loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        p = self.player
        p.loop_mode = (p.loop_mode + 1) % 3
        self.refresh()
        await interaction.response.edit_message(embed=p.build_embed(), view=self)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.secondary, row=0)
    async def btn_stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.player.destroy()

    # ---- row 1 ----
    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.secondary, row=1)
    async def btn_vol_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        p = self.player
        p.change_volume(-0.1)
        await interaction.response.edit_message(embed=p.build_embed(), view=self)

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary, row=1)
    async def btn_vol_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        p = self.player
        p.change_volume(0.1)
        await interaction.response.edit_message(embed=p.build_embed(), view=self)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, row=1)
    async def btn_shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        p = self.player
        items = list(p.queue)
        random.shuffle(items)
        p.queue = deque(items)
        await interaction.response.edit_message(embed=p.build_embed(), view=self)

    @discord.ui.button(emoji="📜", style=discord.ButtonStyle.secondary, row=1)
    async def btn_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        p = self.player
        if not p.queue:
            text = "لیستەکە بەتاڵە ✧"
        else:
            lines = [
                f"`{i}` {clean_title(t.title, 60)} ・ `{fmt_time(t.duration)}`"
                for i, t in enumerate(list(p.queue)[:15], 1)
            ]
            if len(p.queue) > 15:
                lines.append(f"-# + {len(p.queue) - 15} more")
            text = "\n".join(lines)
        embed = discord.Embed(title="✿ Queue", description=text, color=LILAC)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------
# One player per server
# ---------------------------------------------------------
class Player:
    def __init__(self, cog, guild, text_channel):
        self.cog = cog
        self.bot = cog.bot
        self.guild = guild
        self.text_channel = text_channel

        self.queue = deque()
        self.history = []
        self.current: Optional[Track] = None
        self.loop_mode = 0          # 0 off, 1 track, 2 queue
        self.volume = 1.0
        self.action = None          # None | "skip" | "prev"

        self.has_items = asyncio.Event()
        self.done = asyncio.Event()

        self.started = 0.0
        self.paused_at = None
        self.paused_total = 0.0

        self.message: Optional[discord.Message] = None
        self.view = PlayerView(self)
        self.alone_ticks = 0
        self.closed = False
        self.main_task = None
        self.tick_task = None

    # ---- basics ----
    @property
    def vc(self):
        return self.guild.voice_client

    def start(self):
        self.main_task = asyncio.create_task(self._main())
        self.tick_task = asyncio.create_task(self._tick())

    def add(self, track):
        self.queue.append(track)
        self.has_items.set()

    @property
    def elapsed(self):
        if not self.current:
            return 0
        now = self.paused_at if self.paused_at is not None else time.monotonic()
        return max(0, now - self.started - self.paused_total)

    def mark_paused(self):
        if self.paused_at is None:
            self.paused_at = time.monotonic()

    def mark_resumed(self):
        if self.paused_at is not None:
            self.paused_total += time.monotonic() - self.paused_at
            self.paused_at = None

    def change_volume(self, delta):
        self.volume = round(min(MAX_VOLUME, max(0.1, self.volume + delta)), 2)
        vc = self.vc
        if vc and vc.source is not None and hasattr(vc.source, "volume"):
            vc.source.volume = self.volume

    def _after(self, error):
        if error:
            print(f"[music] player error: {error}", flush=True)
        self.bot.loop.call_soon_threadsafe(self.done.set)

    async def _say(self, text):
        if self.text_channel is None:
            return
        try:
            await self.text_channel.send(text, delete_after=15)
        except Exception:
            pass

    # ---- panel ----
    def build_embed(self):
        t = self.current
        if t is None:
            return discord.Embed(
                title="✿ Queue ended ♡",
                description="-# /gorani بۆ ژەندنی گۆرانییەکی نوێ",
                color=LILAC,
            )

        paused = self.paused_at is not None
        total = t.duration
        if total > 0:
            time_line = f"`{fmt_time(self.elapsed)}` {make_bar(self.elapsed, total)} `{fmt_time(total)}`"
        else:
            time_line = f"`LIVE` {make_bar(0, 0)} ♡"

        desc = f"**[{clean_title(t.title)}]({t.page_url})**\n"
        if t.uploader:
            desc += f"-# {t.uploader}\n"
        desc += f"-# ♡ requested by {t.requester}\n\n{time_line}"

        embed = discord.Embed(
            title="⏸ Paused ♡" if paused else "✿ Now Playing ♡",
            description=desc,
            color=LILAC if paused else PINK,
        )
        if t.thumbnail:
            embed.set_thumbnail(url=t.thumbnail)

        if self.queue:
            nxt = [f"`{i}` {clean_title(x.title, 45)}" for i, x in enumerate(list(self.queue)[:3], 1)]
            if len(self.queue) > 3:
                nxt.append(f"-# + {len(self.queue) - 3} more")
            embed.add_field(name="✧ Up next", value="\n".join(nxt), inline=False)

        ping = round(self.bot.latency * 1000) if self.bot.latency == self.bot.latency else 0
        embed.set_footer(
            text=f"Volume {int(self.volume * 100)}%  ·  Loop {LOOP_NAMES[self.loop_mode]}  ·  Ping {ping}ms"
        )
        return embed

    async def refresh_panel(self, ensure=False, idle=False):
        if self.closed:
            return
        embed = self.build_embed()
        view = None
        if not idle:
            self.view.refresh()
            view = self.view
        if self.message is not None:
            try:
                await self.message.edit(embed=embed, view=view)
                return
            except discord.NotFound:
                self.message = None
            except discord.HTTPException:
                return
        if ensure and self.text_channel is not None:
            try:
                self.message = await self.text_channel.send(embed=embed, view=view)
            except Exception:
                pass

    async def _delete_panel(self):
        if self.message is not None:
            try:
                await self.message.delete()
            except Exception:
                pass
            self.message = None

    # ---- main loop ----
    async def _choose_next(self):
        action, self.action = self.action, None
        cur = self.current
        nxt = None

        if cur is not None:
            if action == "prev":
                if self.history:
                    nxt = self.history.pop()
                    self.queue.appendleft(cur)
                    if self.loop_mode == 2 and nxt in self.queue:
                        self.queue.remove(nxt)
                else:
                    nxt = cur
            elif self.loop_mode == 1 and action != "skip":
                nxt = cur
            else:
                self.history.append(cur)
                del self.history[:-25]
                if self.loop_mode == 2:
                    self.queue.append(cur)
        if nxt is not None:
            return nxt

        self.current = None
        if not self.queue:
            await self.refresh_panel(idle=True)
        while not self.queue:
            self.has_items.clear()
            try:
                await asyncio.wait_for(self.has_items.wait(), IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                return None
        return self.queue.popleft()

    async def _main(self):
        try:
            while not self.closed:
                track = await self._choose_next()
                if track is None:
                    break
                vc = self.vc
                if vc is None or not vc.is_connected():
                    break

                try:
                    url = await self.cog.resolve(track)
                except Exception as e:
                    print(f"[music] resolve failed: {e}", flush=True)
                    await self._say(f"نەتوانرا «{clean_title(track.title, 40)}» بکرێتەوە ✧")
                    self.current = None
                    continue

                self.current = track
                self.done.clear()
                self.started = time.monotonic()
                self.paused_at = None
                self.paused_total = 0.0
                try:
                    source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTS)
                    source = discord.PCMVolumeTransformer(source, volume=self.volume)
                    vc.play(source, after=self._after)
                except Exception as e:
                    print(f"[music] play failed: {e}", flush=True)
                    await self._say("نەتوانرا گۆرانییەکە بژەنرێت (FFmpeg؟) ✧")
                    self.current = None
                    continue

                await self.refresh_panel(ensure=True)
                await self.done.wait()
        except asyncio.CancelledError:
            raise
        except Exception:
            traceback.print_exc()
        finally:
            if not self.closed:
                await self.destroy()

    async def _tick(self):
        try:
            while not self.closed:
                await asyncio.sleep(10)
                vc = self.vc
                if vc is None or not vc.is_connected() or vc.channel is None:
                    continue
                humans = [m for m in vc.channel.members if not m.bot]
                if not humans:
                    self.alone_ticks += 1
                    if self.alone_ticks >= ALONE_TICKS:
                        await self._say("کەس لە ڤۆیس نەماوە، دەرچووم ♡")
                        await self.destroy()
                        return
                else:
                    self.alone_ticks = 0
                if self.current and vc.is_playing():
                    await self.refresh_panel()
        except asyncio.CancelledError:
            raise
        except Exception:
            traceback.print_exc()

    async def destroy(self):
        if self.closed:
            return
        self.closed = True
        if self.cog.players.get(self.guild.id) is self:
            self.cog.players.pop(self.guild.id, None)
        me = asyncio.current_task()
        for task in (self.tick_task, self.main_task):
            if task is not None and task is not me:
                task.cancel()
        vc = self.vc
        if vc is not None:
            try:
                vc.stop()
            except Exception:
                pass
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass
        self.queue.clear()
        await self._delete_panel()


# ---------------------------------------------------------
# Cog:  /gorani
# ---------------------------------------------------------
class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.players = {}
        _ensure_opus()
        if shutil.which("ffmpeg") is None:
            print("⚠️ [music] ffmpeg نەدۆزرایەوە! (nixpacks.toml / RAILPACK_DEPLOY_APT_PACKAGES)", flush=True)

    async def cog_unload(self):
        for player in list(self.players.values()):
            await player.destroy()

    async def resolve(self, track):
        if track.stream_url and time.time() - track.resolved_at < 900:
            return track.stream_url
        info = await asyncio.to_thread(_extract, track.page_url)
        track.stream_url = info["url"]
        track.resolved_at = time.time()
        return track.stream_url

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if self.bot.user and member.id == self.bot.user.id and after.channel is None:
            player = self.players.get(member.guild.id)
            if player:
                await player.destroy()

    @app_commands.command(name="gorani", description="ژەندنی گۆرانی لە ڤۆیس 🎵")
    @app_commands.describe(query="ناوی گۆرانی یان لینکی یوتیوب")
    @app_commands.guild_only()
    async def gorani(self, interaction: discord.Interaction, query: str):
        user = interaction.user
        guild = interaction.guild

        if not isinstance(user, discord.Member) or user.voice is None or user.voice.channel is None:
            await interaction.response.send_message(
                "یەکەم بچۆ ناو ڤۆیسێک پاشان /gorani بەکاربهێنە ♡", ephemeral=True
            )
            return

        channel = user.voice.channel
        perms = channel.permissions_for(guild.me)
        if not (perms.connect and perms.speak):
            await interaction.response.send_message(
                "ڕێگەپێدانی Connect و Speak م نییە لەم ڤۆیسە ✧", ephemeral=True
            )
            return

        vc = guild.voice_client
        if vc is not None and vc.channel.id != channel.id and (vc.is_playing() or vc.is_paused()):
            await interaction.response.send_message(
                f"من ئێستا لە {vc.channel.mention} دەژەنم، بچۆ ئەوێ ♡", ephemeral=True
            )
            return

        await interaction.response.defer()

        # 1) search
        try:
            info = await asyncio.to_thread(_extract, query.strip())
        except Exception as e:
            print(f"[music] search failed: {e}", flush=True)
            await interaction.followup.send("نەتوانرا گۆرانییەکە بدۆزرێتەوە ✧", delete_after=10)
            return
        track = info_to_track(info, user.display_name)

        # 2) connect
        try:
            if vc is None:
                vc = await channel.connect(self_deaf=True, timeout=30)
            elif vc.channel.id != channel.id:
                await vc.move_to(channel)
        except Exception as e:
            print(f"[music] connect failed: {e}", flush=True)
            await interaction.followup.send("نەتوانرا بچمە ناو ڤۆیس ✧", delete_after=10)
            return

        # 3) player
        player = self.players.get(guild.id)
        if player is None or player.closed:
            player = Player(self, guild, interaction.channel)
            self.players[guild.id] = player
            player.start()
        else:
            player.text_channel = interaction.channel

        busy = player.current is not None or bool(player.queue)
        position = len(player.queue) + (1 if player.current else 0)
        player.add(track)

        if busy:
            text = f"♡ زیادکرا بۆ لیست  **{clean_title(track.title, 60)}**\n-# #{position} · `{fmt_time(track.duration)}`"
        else:
            text = f"✧ دەست پێدەکات  **{clean_title(track.title, 60)}**"
        await interaction.followup.send(embed=discord.Embed(description=text, color=PINK), delete_after=8)


async def setup(bot):
    if yt_dlp is None:
        raise RuntimeError("yt-dlp نییە — بیخە ناو requirements.txt")
    await bot.add_cog(Music(bot))
