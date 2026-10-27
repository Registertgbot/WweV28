"""Owner moderation: /botban /botunban /botmute /botunmute /banlist, coin / card / skin corrections, /wallet, /auditlog.

The BanGate middleware (registered in bot.py) silently blocks banned and muted users everywhere.
"""
from aiogram import Router
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from config import get_settings
from database import transaction
from models import Wallet, Wrestler, WrestlerOwned, User, UserSkin
from services import economy, moderation
from services import tour_rules as tr
from services.cards import VIP_STYLES
from services.spawns import norm

router = Router(name="moderation")


def _owner_id() -> int:
    return get_settings().owner_id


def _is_owner(message: Message) -> bool:
    return bool(message.from_user) and message.from_user.id == _owner_id()


# --------------------------------------------------------------------------------------------- gate

class BanGate(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user is None or user.id == _owner_id():
            return await handler(event, data)
        hit = moderation.status(user.id)
        if hit is None:
            return await handler(event, data)
        kind, until, reason = hit
        text = ("🚫 You are banned from this bot." if kind == "ban"
                else f"🔇 You are muted until {tr.fmt_ist(until)}." if until else "🔇 You are muted.") + (f"\nReason: {reason}" if reason else "")
        if isinstance(event, CallbackQuery):
            await event.answer(text[:190], show_alert=True)
        elif isinstance(event, Message) and (event.text or "").startswith("/") and moderation.should_notice(user.id):
            await event.answer(text)
        return None


# ------------------------------------------------------------------------------------------- helpers

def _split(message: Message, command: CommandObject, tail_is_id: bool = False):
    """-> (target_user_id | None, remaining args). Target = replied-to user, else the first (or last) numeric argument."""
    args = (command.args or "").split()
    reply = message.reply_to_message
    if reply and reply.from_user and not reply.from_user.is_bot:
        return reply.from_user.id, args
    if tail_is_id and args and args[-1].lstrip("-").isdigit() and len(args[-1]) >= 6:
        return int(args[-1]), args[:-1]
    if not tail_is_id and args and args[0].lstrip("-").isdigit() and len(args[0]) >= 6:
        return int(args[0]), args[1:]
    return None, args


async def _name(session, user_id: int) -> str:
    user = await session.get(User, user_id)
    return f"{user.display_name} (<code>{user_id}</code>)" if user else f"<code>{user_id}</code>"


async def _wrestler(session, name: str):
    n = norm(name)
    rows = (await session.execute(select(Wrestler).where(Wrestler.active.is_(True), Wrestler.name_norm.contains(n)))).scalars().all() if n else []
    exact = [w for w in rows if w.name_norm == n]
    return (exact or rows)[0] if len(exact or rows) == 1 else None, rows


# --------------------------------------------------------------------------------------- ban / mute

@router.message(Command("botban"))
async def cmd_ban(message: Message, command: CommandObject) -> None:
    if not _is_owner(message):
        return
    uid, rest = _split(message, command)
    if uid is None or uid == _owner_id():
        await message.answer("Use <code>/botban [reason]</code> as a reply, or <code>/botban user_id [reason]</code>.")
        return
    reason = " ".join(rest)
    async with transaction() as s:
        await moderation.punish(s, uid, "ban", None, reason, message.from_user.id)
        await moderation.audit(s, message.from_user.id, "ban", uid, reason)
        who = await _name(s, uid)
    await message.answer(f"🚫 Banned {who} from the bot." + (f"\nReason: {reason}" if reason else ""))


@router.message(Command("botmute"))
async def cmd_mute(message: Message, command: CommandObject) -> None:
    if not _is_owner(message):
        return
    uid, rest = _split(message, command)
    minutes = int(rest[0]) if rest and rest[0].isdigit() else 60
    if uid is None or uid == _owner_id():
        await message.answer("Use <code>/botmute [minutes] [reason]</code> as a reply, or <code>/botmute user_id [minutes] [reason]</code>.")
        return
    reason = " ".join(rest[1:] if rest and rest[0].isdigit() else rest)
    async with transaction() as s:
        await moderation.punish(s, uid, "mute", minutes, reason, message.from_user.id)
        await moderation.audit(s, message.from_user.id, "mute", uid, f"{minutes} min {reason}".strip())
        who = await _name(s, uid)
    await message.answer(f"🔇 Muted {who} for {minutes} minutes.")


@router.message(Command("botunban", "botunmute"))
async def cmd_unban(message: Message, command: CommandObject) -> None:
    if not _is_owner(message):
        return
    uid, _ = _split(message, command)
    if uid is None:
        await message.answer("Use <code>/botunban</code> as a reply, or <code>/botunban user_id</code>.")
        return
    async with transaction() as s:
        done = await moderation.lift(s, uid)
        if done:
            await moderation.audit(s, message.from_user.id, "unban", uid)
        who = await _name(s, uid)
    await message.answer(f"✅ {who} can use the bot again." if done else f"{who} was not banned or muted.")


@router.message(Command("banlist"))
async def cmd_banlist(message: Message) -> None:
    if not _is_owner(message):
        return
    async with transaction() as s:
        rows = await moderation.listing(s)
        lines = [f"{'🚫' if r.kind == 'ban' else '🔇'} {await _name(s, r.user_id)}"
                 + (f" until {tr.fmt_ist(r.until)}" if r.until else "") + (f" — {r.reason}" if r.reason else "") for r in rows]
    await message.answer("🧾 <b>Banned / muted</b>\n" + ("\n".join(lines) or "nobody"))


# --------------------------------------------------------------------------------- coins, cards, skins

@router.message(Command("takecoins", "setcoins"))
async def cmd_coins(message: Message, command: CommandObject) -> None:
    if not _is_owner(message):
        return
    uid, rest = _split(message, command, tail_is_id=True)
    if uid is None or not rest or not rest[0].isdigit():
        await message.answer("Use <code>/takecoins 300</code> or <code>/setcoins 1000</code> as a reply, or add the user id at the end.")
        return
    amount = int(rest[0])
    setting = (message.text or "").lstrip("/").lower().startswith("setcoins")
    async with transaction() as s:
        w = await economy.wallet(s, uid)
        before = w.coins
        w.coins = amount if setting else max(0, w.coins - amount)
        await moderation.audit(s, message.from_user.id, "setcoins" if setting else "takecoins", uid, f"{before} -> {w.coins}")
        who, after = await _name(s, uid), w.coins
    await message.answer(f"✅ {who}: {before} ➜ <b>{after}</b> coins.")


@router.message(Command("givecard", "takecard"))
async def cmd_card(message: Message, command: CommandObject) -> None:
    if not _is_owner(message):
        return
    uid, rest = _split(message, command, tail_is_id=True)
    giving = (message.text or "").lstrip("/").lower().startswith("givecard")
    if uid is None or not rest:
        await message.answer("Use <code>/givecard John Cena</code> as a reply, or <code>/givecard John Cena 123456789</code>.")
        return
    async with transaction() as s:
        w, candidates = await _wrestler(s, " ".join(rest))
        if w is None:
            await message.answer("No single wrestler matches that name." if not candidates else
                                 "Be more exact: " + ", ".join(c.name for c in candidates[:8]))
            return
        owned = await s.get(WrestlerOwned, (uid, w.id))
        if giving:
            if owned is None:
                s.add(WrestlerOwned(user_id=uid, wrestler_id=w.id, qty=1))
            else:
                owned.qty += 1
        elif owned is None:
            await message.answer("He does not own that card.")
            return
        elif owned.qty > 1:
            owned.qty -= 1
        else:
            await s.delete(owned)
        await moderation.audit(s, message.from_user.id, "givecard" if giving else "takecard", uid, w.name)
        who = await _name(s, uid)
    await message.answer(f"✅ {w.name} {'given to' if giving else 'taken from'} {who}.")


@router.message(Command("giveskin", "takeskin"))
async def cmd_skin(message: Message, command: CommandObject) -> None:
    if not _is_owner(message):
        return
    uid, rest = _split(message, command, tail_is_id=True)
    giving = (message.text or "").lstrip("/").lower().startswith("giveskin")
    key = rest[0] if rest else ""
    if uid is None or key not in VIP_STYLES:
        await message.answer("Use <code>/giveskin key</code> (reply or user id at the end). Skins: " + ", ".join(f"<code>{k}</code>" for k in VIP_STYLES))
        return
    async with transaction() as s:
        have = await s.get(UserSkin, (uid, key))
        if giving and have is None:
            s.add(UserSkin(user_id=uid, skin=key))
        elif not giving and have is not None:
            await s.delete(have)
            w = await s.get(Wallet, uid)
            if w is not None and w.skin == key:
                w.skin = None
        await moderation.audit(s, message.from_user.id, "giveskin" if giving else "takeskin", uid, key)
        who = await _name(s, uid)
    await message.answer(f"✅ {economy.skin_name(key)} {'given to' if giving else 'taken from'} {who}.")


@router.message(Command("wallet"))
async def cmd_wallet(message: Message, command: CommandObject) -> None:
    if not _is_owner(message):
        return
    uid, _ = _split(message, command)
    if uid is None:
        await message.answer("Use <code>/wallet</code> as a reply, or <code>/wallet user_id</code>.")
        return
    async with transaction() as s:
        who = await _name(s, uid)
        w = await s.get(Wallet, uid)
        cards = (await s.execute(select(WrestlerOwned).where(WrestlerOwned.user_id == uid))).scalars().all()
        skins = await economy.owned_skins(s, uid)
        hit = moderation.status(uid)
    await message.answer(f"👛 <b>{who}</b>\n💰 Coins: <b>{w.coins if w else 0}</b>\n🃏 Wrestlers: {len(cards)} "
                         f"({sum(c.qty for c in cards)} cards)\n🎨 Skins: {', '.join(sorted(skins)) or 'none'}"
                         + (f"\n🚫 Status: {hit[0]}" if hit else ""))


@router.message(Command("auditlog"))
async def cmd_audit(message: Message, command: CommandObject) -> None:
    if not _is_owner(message):
        return
    n = int(command.args) if (command.args or "").strip().isdigit() else 15
    async with transaction() as s:
        rows = await moderation.recent_audit(s, min(n, 40))
    lines = [f"{tr.fmt_ist(r.at)} • <b>{r.action}</b> • <code>{r.target_id or '-'}</code> {r.detail or ''}" for r in rows]
    await message.answer("📜 <b>Audit log</b>\n" + ("\n".join(lines) or "empty"))
