import discord
from discord import app_commands
import asyncio
import io
import math
import random

# پێویستی بە Pillow هەیە (لە requirements.txt بنووسە: Pillow)
from PIL import Image, ImageDraw, ImageFilter

# =========================================================
# DOMINO GAME  (/domino)  - بە وێنەی ڕاستەقینەی پولەکان
# =========================================================

# ---- RENDER-START ----
# وێنەی مێز و پولەکان دەکێشرێت (Pillow) - وەک یاری دۆمینەی ڕاستەقینە

S = 2                      # supersampling (جوانتر دەکات)
TW, TH = 130, 66           # قەبارەی یەک پول
GAP = 14
ROW_GAP = 22
MARGIN = 36
BOARD_PER_ROW = 6
HAND_PER_ROW = 5

PIP_COLORS = {
    1: (37, 99, 235),
    2: (22, 163, 74),
    3: (220, 38, 38),
    4: (217, 119, 6),
    5: (124, 58, 237),
    6: (15, 23, 42),
}

PIP_GRID = {
    1: [(.5, .5)],
    2: [(.27, .27), (.73, .73)],
    3: [(.27, .27), (.5, .5), (.73, .73)],
    4: [(.27, .27), (.73, .27), (.27, .73), (.73, .73)],
    5: [(.27, .27), (.73, .27), (.5, .5), (.27, .73), (.73, .73)],
    6: [(.27, .22), (.73, .22), (.27, .5), (.73, .5), (.27, .78), (.73, .78)],
}


def _felt(w, h):
    base = Image.new("RGB", (w, h), (16, 98, 62))
    dark = Image.new("RGB", (w, h), (3, 32, 21))
    vign = Image.radial_gradient("L").resize((w, h)).point(lambda p: int(p * 0.8))
    img = Image.composite(dark, base, vign)
    d = ImageDraw.Draw(img)
    # قەراغی دار
    d.rectangle([0, 0, w - 1, h - 1], outline=(96, 60, 28), width=10 * S)
    d.rectangle([10 * S, 10 * S, w - 1 - 10 * S, h - 1 - 10 * S], outline=(58, 34, 14), width=2 * S)
    return img.convert("RGBA")


def _draw_pips(d, value, ox, oy, pw, ph):
    if value == 0:
        return
    col = PIP_COLORS[value]
    r = 6.5 * S
    for fx, fy in PIP_GRID[value]:
        px, py = ox + fx * pw, oy + fy * ph
        d.ellipse([px - r, py - r, px + r, py + r], fill=col)
        d.ellipse([px - r * 0.45 - r * 0.25, py - r * 0.55 - r * 0.25,
                   px - r * 0.45 + r * 0.25, py - r * 0.55 + r * 0.25], fill=(255, 255, 255))


def _draw_tile(d, x, y, a, b):
    w, h = TW * S, TH * S
    rad = 12 * S
    d.rounded_rectangle([x, y, x + w, y + h], rad, fill=(250, 247, 238),
                        outline=(200, 192, 168), width=2 * S)
    d.rounded_rectangle([x + 4 * S, y + 4 * S, x + w - 4 * S, y + h - 4 * S], rad - 4 * S,
                        outline=(255, 255, 255), width=S)
    cx = x + w / 2
    d.line([cx, y + 9 * S, cx, y + h - 9 * S], fill=(176, 168, 144), width=2 * S)
    d.ellipse([cx - 3 * S, y + h / 2 - 3 * S, cx + 3 * S, y + h / 2 + 3 * S], fill=(184, 150, 70))
    _draw_pips(d, a, x, y, w / 2, h)
    _draw_pips(d, b, cx, y, w / 2, h)


def _render(specs, width, height):
    """specs: [(x, y, a, b, mode)] - mode: normal / end / playable / dim"""
    W, H = width * S, height * S
    img = _felt(W, H)

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for x, y, a, b, mode in specs:
        X, Y = x * S, y * S
        sd.rounded_rectangle([X + 3 * S, Y + 6 * S, X + TW * S + 3 * S, Y + TH * S + 6 * S],
                             12 * S, fill=(0, 0, 0, 150))
        if mode in ("end", "playable"):
            c = (255, 205, 40, 255) if mode == "end" else (90, 235, 130, 255)
            gd.rounded_rectangle([X - 5 * S, Y - 5 * S, X + TW * S + 5 * S, Y + TH * S + 5 * S],
                                 16 * S, fill=c)
    shadow = shadow.filter(ImageFilter.GaussianBlur(6 * S))
    glow_blur = glow.filter(ImageFilter.GaussianBlur(6 * S))
    img = Image.alpha_composite(img, shadow)
    img = Image.alpha_composite(img, glow_blur)

    d = ImageDraw.Draw(img)
    for x, y, a, b, mode in specs:
        X, Y = x * S, y * S
        if mode in ("end", "playable"):
            c = (255, 205, 40) if mode == "end" else (90, 235, 130)
            d.rounded_rectangle([X - 3 * S, Y - 3 * S, X + TW * S + 3 * S, Y + TH * S + 3 * S],
                                15 * S, outline=c, width=3 * S)
        _draw_tile(d, X, Y, a, b)

    dim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dim)
    for x, y, a, b, mode in specs:
        if mode == "dim":
            X, Y = x * S, y * S
            dd.rounded_rectangle([X, Y, X + TW * S, Y + TH * S], 12 * S, fill=(10, 20, 15, 150))
    img = Image.alpha_composite(img, dim)

    img = img.convert("RGB").resize((width, height), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def render_board_png(board):
    n = len(board)
    rows = max(1, math.ceil(n / BOARD_PER_ROW))
    width = MARGIN * 2 + BOARD_PER_ROW * TW + (BOARD_PER_ROW - 1) * GAP
    height = MARGIN * 2 + rows * TH + (rows - 1) * ROW_GAP
    specs = []
    for i, (a, b) in enumerate(board):
        r, k = divmod(i, BOARD_PER_ROW)
        slot = k if r % 2 == 0 else BOARD_PER_ROW - 1 - k
        x = MARGIN + slot * (TW + GAP)
        y = MARGIN + r * (TH + ROW_GAP)
        if r % 2 == 1:           # ڕیزی دووەم بە پێچەوانە دەڕوات
            a, b = b, a
        mode = "end" if i in (0, n - 1) else "normal"
        specs.append((x, y, a, b, mode))
    return _render(specs, width, height)


def render_hand_png(hand, playable):
    """playable: set of tiles that can be played (None = no highlighting)"""
    n = max(1, len(hand))
    cols = max(3, min(n, HAND_PER_ROW))
    rows = max(1, math.ceil(n / HAND_PER_ROW))
    width = MARGIN * 2 + cols * TW + (cols - 1) * GAP
    height = MARGIN * 2 + rows * TH + (rows - 1) * ROW_GAP
    specs = []
    for i, t in enumerate(hand):
        r, k = divmod(i, HAND_PER_ROW)
        x = MARGIN + k * (TW + GAP)
        y = MARGIN + r * (TH + ROW_GAP)
        if playable:
            mode = "playable" if t in playable else "dim"
        else:
            mode = "normal"
        specs.append((x, y, t[0], t[1], mode))
    return _render(specs, width, height)
# ---- RENDER-END ----


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
            return "ئەم پولە لە دەستتدا نییە."
        if side not in self.playable_sides(tile):
            return "ئەم پولە لەم لایەدا ناگونجێت."

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
            return None, "پولی گونجاوت هەیە، دەبێت یاری بکەیت."
        if not self.boneyard:
            return None, "پولی ماوە نەماوە، Pass بکە."
        tile = self.boneyard.pop()
        self.hands[uid] = sorted(self.hands[uid] + [tile])
        self.last = f"🎴 <@{uid}> پولێکی هەڵگرت"
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

BOARD_COLOR = 0x1B7F4B
HAND_COLOR = 0x2B2D31


async def _file(func, *args, name):
    data = await asyncio.to_thread(func, *args)
    return discord.File(io.BytesIO(data), filename=name)


def domino_tile_text(tile):
    return f"[{tile[0]}|{tile[1]}]"


async def board_file(game):
    return await _file(render_board_png, list(game.board), name="board.png")


def domino_embed(game):
    left, right = game.ends()
    e = discord.Embed(
        title="🎲 Domino",
        color=discord.Color.gold() if game.finished else discord.Color(BOARD_COLOR)
    )
    e.set_image(url="attachment://board.png")

    lines = []
    for i, uid in enumerate(game.players):
        mark = "▶️" if (not game.finished and i == game.turn) else "▫️"
        lines.append(f"{mark} <@{uid}> — `{len(game.hands[uid])}` 🁢")
    e.add_field(name="یاریزانان", value="\n".join(lines), inline=True)

    info = f"📦 پولی ماوە: `{len(game.boneyard)}`"
    if left is not None:
        info += f"\n🎯 کۆتاییەکان: `{left}` ⬌ `{right}`"
    e.add_field(name="مێز", value=info, inline=True)

    if game.last:
        e.add_field(name="دوایین کار", value=game.last, inline=False)

    if game.finished:
        left_over = "\n".join(
            f"<@{u}>: " + (" ".join(domino_tile_text(t) for t in game.hands[u]) or "—")
            for u in game.players
        )
        e.add_field(name="ئەنجام", value=game.result, inline=False)
        e.add_field(name="پولەکانی ماوە", value=left_over, inline=False)
    else:
        e.set_footer(text="دوگمەی «My Hand» دابگرە بۆ بینینی پولەکانت")
    return e


async def domino_refresh(game):
    """Update the public game message."""
    try:
        if game.message is None:
            return
        f = await board_file(game)
        await game.message.edit(
            embed=domino_embed(game),
            attachments=[f],
            view=None if game.finished else DominoGameView(game),
            allowed_mentions=discord.AllowedMentions.none()
        )
    except Exception as e:
        print(f"domino_refresh error: {e}", flush=True)
    if game.finished:
        domino_cleanup(game)


def domino_cleanup(game):
    if _domino_games.get(game.channel.id) is game:
        _domino_games.pop(game.channel.id, None)


def domino_hand_status(game, uid):
    if game.finished:
        return game.result
    if game.current() == uid:
        if game.playable_tiles(uid):
            return "🟢 نۆرەی تۆیە، پولێک هەڵبژێرە."
        if game.boneyard:
            return "🟡 پولی گونجاوت نییە، **Draw** بکە."
        return "🟠 پولی گونجاوت نییە و پولی ماوە نەماوە، **Pass** بکە."
    return f"⏳ چاوەڕێی <@{game.current()}> بکە."


async def hand_payload(game, uid, note=""):
    """Returns (embed, file) for the private hand message."""
    hand = list(game.hands.get(uid, []))
    playable = None
    if not game.finished and game.current() == uid:
        p = game.playable_tiles(uid)
        playable = set(p) if p else None
    f = await _file(render_hand_png, hand, playable, name="hand.png")

    left, right = game.ends()
    desc = [x for x in (note, domino_hand_status(game, uid)) if x]
    if left is not None:
        desc.append(f"🎯 کۆتاییەکانی مێز: `{left}` ⬌ `{right}`")
    e = discord.Embed(title="🀄 پولەکانت", description="\n".join(desc),
                      color=discord.Color(HAND_COLOR))
    e.set_image(url="attachment://hand.png")
    return e, f


def domino_parse_tile(value):
    a, b = value.split("-")
    return tuple(sorted((int(a), int(b))))


async def hand_edit(interaction, game, uid, note=""):
    embed, f = await hand_payload(game, uid, note)
    await interaction.response.edit_message(
        content=None, embed=embed, attachments=[f],
        view=DominoHandView(game, uid),
        allowed_mentions=discord.AllowedMentions.none()
    )


async def domino_do_move(interaction, game, uid, tile, side):
    async with game.lock:
        err = game.play(uid, tile, side)
    if err:
        await interaction.response.edit_message(
            content=f"❌ {err}", view=DominoHandView(game, uid))
        return
    await hand_edit(interaction, game, uid, f"✅ `{domino_tile_text(tile)}` دانرا")
    await domino_refresh(game)


class DominoTileSelect(discord.ui.Select):
    def __init__(self, game, uid, tiles):
        opts = []
        for t in tiles[:25]:
            sides = game.playable_sides(t)
            where = "/".join("ڕاست" if s == "R" else "چەپ" for s in sides)
            opts.append(discord.SelectOption(
                label=f"{t[0]}  |  {t[1]}", value=f"{t[0]}-{t[1]}",
                description=where, emoji="🁣"))
        super().__init__(placeholder="پولێک هەڵبژێرە...", options=opts)
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
                content="❌ ئەم پولە ناگونجێت.", view=DominoHandView(game, uid))


class DominoDrawButton(discord.ui.Button):
    def __init__(self, game, uid):
        super().__init__(label="Draw (هەڵگرتنی پول)", style=discord.ButtonStyle.primary, emoji="🎴")
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
        await hand_edit(interaction, game, uid, f"🎴 پولی `{domino_tile_text(tile)}` ت هەڵگرت")
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
        await hand_edit(interaction, game, uid, "⏭️ Pass ت کرد")
        await domino_refresh(game)


class DominoHandView(discord.ui.View):
    """Private (ephemeral) hand of one player."""
    def __init__(self, game, uid):
        super().__init__(timeout=600)
        if game.finished or game.current() != uid:
            return
        playable = game.playable_tiles(uid)
        if playable:
            self.add_item(DominoTileSelect(game, uid, playable))
        elif game.boneyard:
            self.add_item(DominoDrawButton(game, uid))
        else:
            self.add_item(DominoPassButton(game, uid))


class DominoSideView(discord.ui.View):
    """When a tile fits both ends, choose the side."""
    def __init__(self, game, uid, tile):
        super().__init__(timeout=600)
        self.game, self.uid, self.tile = game, uid, tile

    @discord.ui.button(label="چەپ", emoji="⬅️", style=discord.ButtonStyle.primary)
    async def left_btn(self, interaction, button):
        await domino_do_move(interaction, self.game, self.uid, self.tile, "L")

    @discord.ui.button(label="ڕاست", emoji="➡️", style=discord.ButtonStyle.primary)
    async def right_btn(self, interaction, button):
        await domino_do_move(interaction, self.game, self.uid, self.tile, "R")

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_btn(self, interaction, button):
        await hand_edit(interaction, self.game, self.uid)


def domino_lobby_embed(game):
    players = "\n".join(f"🎴 <@{u}>" for u in game.players)
    e = discord.Embed(
        title="🎲 Domino",
        description=(
            f"یاریزانان `{len(game.players)}/{game.MAX_PLAYERS}`:\n{players}\n\n"
            f"دوگمەی **Join** دابگرە بۆ بەشداربوون.\n"
            f"خاوەنی یاریەکە (<@{game.host_id}>) **Start** دادەگرێت (لانیکەم 2 کەس)."
        ),
        color=discord.Color(BOARD_COLOR)
    )
    return e


class DominoLobbyView(discord.ui.View):
    def __init__(self, game):
        super().__init__(timeout=600)
        self.game = game

    @discord.ui.button(label="Join", emoji="✋", style=discord.ButtonStyle.success)
    async def join_btn(self, interaction, button):
        g = self.game
        uid = interaction.user.id
        if g.started:
            await interaction.response.send_message("❌ یاریەکە دەستی پێکردووە.", ephemeral=True)
            return
        if uid in g.players:
            await interaction.response.send_message("⚠ تۆ پێشتر بەشداریت.", ephemeral=True)
            return
        if len(g.players) >= g.MAX_PLAYERS:
            await interaction.response.send_message("❌ یاریەکە پڕە.", ephemeral=True)
            return
        g.players.append(uid)
        await interaction.response.edit_message(
            embed=domino_lobby_embed(g), view=self,
            allowed_mentions=discord.AllowedMentions.none()
        )

    @discord.ui.button(label="Start", emoji="▶️", style=discord.ButtonStyle.primary)
    async def start_btn(self, interaction, button):
        g = self.game
        if interaction.user.id != g.host_id:
            await interaction.response.send_message("❌ تەنها خاوەنی یاریەکە دەتوانێت Start بکات.", ephemeral=True)
            return
        if len(g.players) < 2:
            await interaction.response.send_message("❌ پێویستت بە 2 یاریزان هەیە لانیکەم.", ephemeral=True)
            return
        g.deal()
        self.stop()
        f = await board_file(g)
        await interaction.response.edit_message(
            embed=domino_embed(g), attachments=[f], view=DominoGameView(g),
            allowed_mentions=discord.AllowedMentions.none()
        )
        # Message ی ئاسایی (نەک interaction) بۆ ئەوەی دوای 15 خولەک بەردەوام بێت
        if interaction.message is not None:
            g.message = interaction.message

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.danger)
    async def cancel_btn(self, interaction, button):
        g = self.game
        if interaction.user.id != g.host_id:
            await interaction.response.send_message("❌ تەنها خاوەنی یاریەکە.", ephemeral=True)
            return
        domino_cleanup(g)
        self.stop()
        await interaction.response.edit_message(content="❌ یاریەکە هەڵوەشێنرایەوە.", embed=None, view=None)

    async def on_timeout(self):
        g = self.game
        if not g.started:
            domino_cleanup(g)
            try:
                if g.message:
                    await g.message.edit(content="⌛ کاتی یاریەکە تەواو بوو.", embed=None, view=None)
            except Exception:
                pass


class DominoGameView(discord.ui.View):
    """Public buttons under the game message."""
    def __init__(self, game):
        super().__init__(timeout=None)
        self.game = game

    @discord.ui.button(label="My Hand", emoji="🀄", style=discord.ButtonStyle.primary)
    async def hand_btn(self, interaction, button):
        g = self.game
        uid = interaction.user.id
        if uid not in g.players:
            await interaction.response.send_message("❌ تۆ لەم یاریەدا نیت.", ephemeral=True)
            return
        embed, f = await hand_payload(g, uid)
        await interaction.response.send_message(
            embed=embed, file=f,
            view=DominoHandView(g, uid),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none()
        )

    @discord.ui.button(label="End Game", emoji="🛑", style=discord.ButtonStyle.danger)
    async def end_btn(self, interaction, button):
        g = self.game
        u = interaction.user
        is_admin = u.id == u.guild.owner_id or u.guild_permissions.administrator
        if u.id != g.host_id and not is_admin:
            await interaction.response.send_message("❌ تەنها خاوەنی یاریەکە.", ephemeral=True)
            return
        g.finished = True
        g.result = "🛑 یاریەکە کۆتایی پێهێنرا."
        f = await board_file(g)
        await interaction.response.edit_message(
            embed=domino_embed(g), attachments=[f], view=None,
            allowed_mentions=discord.AllowedMentions.none()
        )
        domino_cleanup(g)


@app_commands.command(name="domino", description="دەستپێکردنی یاری دۆمینۆ")
@app_commands.guild_only()
async def domino_cmd(interaction: discord.Interaction):
    ch = interaction.channel
    if ch.id in _domino_games:
        await interaction.response.send_message(
            "❌ لەم کەناڵە یاریەک چالاکە.", ephemeral=True)
        return
    game = DominoGame(ch, interaction.user.id)
    _domino_games[ch.id] = game
    await interaction.response.send_message(
        embed=domino_lobby_embed(game),
        view=DominoLobbyView(game),
        allowed_mentions=discord.AllowedMentions.none()
    )
    game.message = await interaction.original_response()


async def setup(bot):
    bot.tree.add_command(domino_cmd)
