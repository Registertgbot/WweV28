"""Collectible wrestlers: a card appears in the group every N minutes, the first correct /collect name wins it."""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import random
import re
from pathlib import Path
from datetime import timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, InlineKeyboardButton as B, InlineKeyboardMarkup as M
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import transaction
from models import SpawnGroup, Wrestler, WrestlerOwned, WrestlerSpawn, utcnow
from services import access

log = logging.getLogger(__name__)
RARITY = {"common": ("⚪ Common", 60), "rare": ("🔵 Rare", 25), "epic": ("🟣 Epic", 12), "legendary": ("🟡 Legendary", 3)}
POLL_SECONDS = 30
ROSTER_DIR = Path(__file__).resolve().parent.parent / "assets" / "roster"
LOCAL = "local:"                                      # file_id placeholder: the picture still has to be uploaded to Telegram
DEFAULT_INTERVAL = 30
_active: dict[int, str] = {}              # chat_id -> name of the wrestler waiting to be collected (answers need no DB hit)


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def is_correct(guess: str, name: str) -> bool:
    """Full name, or one distinctive word of it (4+ letters), ignoring case and punctuation."""
    g = norm(guess)
    if not g:
        return False
    if g == norm(name):
        return True
    return len(g) >= 4 and any(norm(w) == g for w in re.split(r"[\s\-]+", name) if len(norm(w)) >= 4)


def rarity_label(key: str) -> str:
    return RARITY.get(key, RARITY["common"])[0]


def hint(name: str) -> str:
    return "  ".join(w[0].upper() + " _" * (len(w) - 1) for w in name.split())


def active_name(chat_id: int) -> str | None:
    return _active.get(chat_id)


def is_guess(chat_id: int, text: str) -> bool:
    name = _active.get(chat_id)
    return bool(name) and len(text) <= 40 and is_correct(text, name)


async def load_active(session: AsyncSession) -> None:
    """After a restart: remember which wrestlers are still waiting in each group."""
    rows = (await session.execute(select(WrestlerSpawn).where(WrestlerSpawn.expired.is_(False), WrestlerSpawn.claimed_by.is_(None))
                                  .order_by(WrestlerSpawn.id))).scalars().all()
    for sp in rows:
        w = await session.get(Wrestler, sp.wrestler_id)
        if w is not None:
            _active[sp.chat_id] = w.name


def spawn_caption() -> str:
    return ("💠 <b>A NEW WRESTLER HAS APPEARED!</b> 💠\n\n"
            "Type his <b>name</b> in the chat to collect him!")


def spawn_kb(spawn_id: int) -> M:
    return M(inline_keyboard=[[B(text="💡 Hint", callback_data=f"wc:h:{spawn_id}")]])


# ---------------------------------------------------------------------------------------- pictures

async def media_for(w: Wrestler, reveal: bool = True):
    """What to pass to send_photo. Bundled wrestlers are drawn as a proper card (cut-out on an arena backdrop, rarity frame,
    name plate); ``reveal=False`` hides the name for the spawn. Pictures added from Telegram are sent as they are."""
    if not w.file_id.startswith(LOCAL):
        return w.file_id
    from services import cards
    data = (ROSTER_DIR / w.file_id[len(LOCAL):]).read_bytes()
    jpeg = await asyncio.to_thread(cards.render_wrestler_card, data, w.name, w.rarity, w.brand, reveal)
    return BufferedInputFile(jpeg, filename="wrestler.jpg")


async def remember_file_id(wrestler_id: int, message) -> None:
    """After the first upload keep Telegram's own file_id so later sends are instant."""
    if getattr(message, "photo", None):
        async with transaction() as s:
            row = await s.get(Wrestler, wrestler_id)
            if row is not None and row.file_id.startswith(LOCAL):
                row.file_id = message.photo[-1].file_id


async def import_roster(session: AsyncSession) -> int:
    """Load assets/roster/roster.csv (file,name,rarity,brand): every new wrestler becomes a collectible card."""
    path = ROSTER_DIR / "roster.csv"
    if not path.is_file():
        return 0
    known = set((await session.execute(select(Wrestler.name_norm))).scalars().all())      # deleted ones stay deleted
    added = 0
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            name, file = (row.get("name") or "").strip(), (row.get("file") or "").strip()
            if not name or not (ROSTER_DIR / file).is_file() or norm(name)[:64] in known:
                continue
            rarity = (row.get("rarity") or "common").strip().lower()
            session.add(Wrestler(name=name[:64], name_norm=norm(name)[:64], rarity=rarity if rarity in RARITY else "common",
                                 brand=(row.get("brand") or "").strip()[:32] or None, file_id=LOCAL + file))
            known.add(norm(name)[:64])
            added += 1
    return added


# -------------------------------------------------------------------------------------------- owner

async def add_wrestler(session: AsyncSession, name: str, rarity: str, brand: str | None, file_id: str) -> Wrestler:
    row = Wrestler(name=name[:64], name_norm=norm(name)[:64], rarity=rarity, brand=(brand or None) and brand[:32],
                   file_id=file_id)
    session.add(row)
    await session.flush()
    return row


async def delete_wrestler(session: AsyncSession, name: str) -> int:
    rows = (await session.execute(select(Wrestler).where(Wrestler.name_norm == norm(name), Wrestler.active.is_(True)))).scalars().all()
    for r in rows:
        r.active = False
    return len(rows)


async def set_group(session: AsyncSession, chat_id: int, enabled: bool, minutes: int | None) -> SpawnGroup:
    row = await session.get(SpawnGroup, chat_id)
    if row is None:
        row = SpawnGroup(chat_id=chat_id)
        session.add(row)
    row.enabled = enabled
    if minutes:
        row.interval_min = max(5, min(minutes, 1440))
    row.interval_min = row.interval_min or DEFAULT_INTERVAL
    row.next_at = utcnow() + timedelta(minutes=1) if enabled else None
    return row


# ------------------------------------------------------------------------------------------- spawning

async def spawn(bot: Bot, chat_id: int) -> bool:
    async with transaction() as s:
        wrestlers = (await s.execute(select(Wrestler).where(Wrestler.active.is_(True)))).scalars().all()
        if not wrestlers:
            return False
        last = (await s.execute(select(WrestlerSpawn).where(WrestlerSpawn.chat_id == chat_id)
                                .order_by(WrestlerSpawn.id.desc()).limit(1))).scalars().first()
        pool = [w for w in wrestlers if len(wrestlers) == 1 or not last or w.id != last.wrestler_id]
        pick = random.choices(pool, weights=[RARITY.get(w.rarity, RARITY["common"])[1] for w in pool])[0]
        old = (await s.execute(select(WrestlerSpawn).where(WrestlerSpawn.chat_id == chat_id, WrestlerSpawn.expired.is_(False),
                                                           WrestlerSpawn.claimed_by.is_(None)))).scalars().all()
        gone = []
        for o in old:
            o.expired = True
            gone.append((o.message_id, o.wrestler_id))
        names = {w.id: w.name for w in wrestlers}
        row = WrestlerSpawn(chat_id=chat_id, wrestler_id=pick.id)
        s.add(row)
        await s.flush()
        spawn_id, wrestler_id, pick_name = row.id, pick.id, pick.name
        media = await media_for(pick, reveal=False)
    for message_id, wid in gone:                                           # the one nobody caught gets revealed
        if message_id and wid in names:
            try:
                await bot.edit_message_caption(chat_id=chat_id, message_id=message_id,
                                               caption=f"💨 Nobody caught <b>{names[wid]}</b> in time.", reply_markup=None)
            except TelegramAPIError:
                pass
    try:
        msg = await bot.send_photo(chat_id, media, caption=spawn_caption(), reply_markup=spawn_kb(spawn_id))
    except TelegramAPIError as exc:
        log.warning("Spawn in %s failed: %s", chat_id, exc)
        async with transaction() as s:
            bad = await s.get(WrestlerSpawn, spawn_id)
            if bad:
                bad.expired = True
        return False
    async with transaction() as s:
        row = await s.get(WrestlerSpawn, spawn_id)
        row.message_id = msg.message_id
    _active[chat_id] = pick_name
    return True


async def tick(bot: Bot) -> None:
    now = utcnow()
    async with transaction() as s:
        due = (await s.execute(select(SpawnGroup).where(SpawnGroup.enabled.is_(True),
                                                        (SpawnGroup.next_at.is_(None)) | (SpawnGroup.next_at <= now)))).scalars().all()
        todo = [(g.chat_id, g.interval_min) for g in due]
        for g in due:
            g.next_at = now + timedelta(minutes=g.interval_min or DEFAULT_INTERVAL)
    for chat_id, _ in todo:
        if access.is_allowed(chat_id):
            await spawn(bot, chat_id)


async def deadline_loop(bot: Bot) -> None:
    while True:
        try:
            await tick(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Spawn loop error")
        await asyncio.sleep(POLL_SECONDS)


# ------------------------------------------------------------------------------------------ collecting

async def claim(session: AsyncSession, chat_id: int, user_id: int, guess: str):
    """-> (status, wrestler, qty): status is none | wrong | late | ok."""
    sp = (await session.execute(select(WrestlerSpawn).where(WrestlerSpawn.chat_id == chat_id, WrestlerSpawn.expired.is_(False))
                                .order_by(WrestlerSpawn.id.desc()).limit(1))).scalars().first()
    if sp is None:
        _active.pop(chat_id, None)
        return "none", None, 0
    w = await session.get(Wrestler, sp.wrestler_id)
    if sp.claimed_by is not None or w is None:
        _active.pop(chat_id, None)
        return "late", w, 0
    if not is_correct(guess, w.name):
        return "wrong", None, 0
    won = await session.execute(update(WrestlerSpawn).where(WrestlerSpawn.id == sp.id, WrestlerSpawn.claimed_by.is_(None))
                                .values(claimed_by=user_id, claimed_at=utcnow()))
    if won.rowcount != 1:
        _active.pop(chat_id, None)
        return "late", w, 0
    _active.pop(chat_id, None)
    owned = await session.get(WrestlerOwned, (user_id, w.id))
    if owned is None:
        session.add(WrestlerOwned(user_id=user_id, wrestler_id=w.id, qty=1))
        return "ok", w, 1
    owned.qty += 1
    return "ok", w, owned.qty


async def hint_for(session: AsyncSession, spawn_id: int) -> str | None:
    sp = await session.get(WrestlerSpawn, spawn_id)
    if sp is None or sp.claimed_by is not None or sp.expired:
        return None
    w = await session.get(Wrestler, sp.wrestler_id)
    return hint(w.name) if w else None


async def collection(session: AsyncSession, user_id: int) -> list[tuple[Wrestler, int]]:
    rows = (await session.execute(select(Wrestler, WrestlerOwned.qty).join(WrestlerOwned, WrestlerOwned.wrestler_id == Wrestler.id)
                                  .where(WrestlerOwned.user_id == user_id))).all()
    order = list(RARITY)[::-1]
    return sorted(((w, q) for w, q in rows), key=lambda r: (order.index(r[0].rarity) if r[0].rarity in order else 9, r[0].name))
