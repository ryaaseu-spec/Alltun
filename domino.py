import discord
from discord import app_commands
import asyncio
import random

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
        await interaction.response.edit_message(
            content=domino_hand_text(self.game, self.uid),
            view=DominoHandView(self.game, self.uid),
            allowed_mentions=discord.AllowedMentions.none()
        )


def domino_lobby_embed(game):
    players = "\n".join(f"▫️ <@{u}>" for u in game.players)
    e = discord.Embed(
        title="🁣 Domino",
        description=(
            f"یاریزانان `{len(game.players)}/{game.MAX_PLAYERS}`:\n{players}\n\n"
            f"دوگمەی **Join** دابگرە بۆ بەشداربوون.\n"
            f"خاوەنی یاریەکە (<@{game.host_id}>) **Start** دادەگرێت (کەمتر نا لە 2 کەس)."
        ),
        color=discord.Color.blurple()
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
        await interaction.response.edit_message(
            embed=domino_embed(g), view=DominoGameView(g),
            allowed_mentions=discord.AllowedMentions.none()
        )

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
        await interaction.response.send_message(
            domino_hand_text(g, uid),
            view=DominoHandView(g, uid),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none()
        )

    @discord.ui.button(label="End Game", emoji="🛑", style=discord.ButtonStyle.danger)
    async def end_btn(self, interaction, button):
        g = self.game
        u = interaction.user
        if u.id != g.host_id and not (u.id == u.guild.owner_id or u.guild_permissions.administrator):
            await interaction.response.send_message("❌ تەنها خاوەنی یاریەکە.", ephemeral=True)
            return
        g.finished = True
        g.result = "🛑 یاریەکە کۆتایی پێهێنرا."
        await interaction.response.edit_message(
            embed=domino_embed(g), view=None,
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
