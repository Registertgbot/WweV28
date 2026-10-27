"""/collect, /mycollection, hint button, and the owner's wrestler-card management."""
import re

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton as B, InlineKeyboardMarkup as M, Message
from sqlalchemy import func, select

from config import get_settings
from database import transaction
from models import Wrestler
from services import economy, spawns
from services import season as season_svc

router = Router(name="collect")
PAGE = 12
_last_wrong: dict[tuple[int, int], float] = {}


def _owner(message: Message) -> bool:
    return bool(message.from_user) and message.from_user.id == get_settings().owner_id


# ------------------------------------------------------------------------------------------- players

async def _award(message: Message, w, qty: int, coins: int = 0, gain_line: str = "") -> None:
    who = message.from_user
    caption = (f"🎉 <b>{who.full_name}</b>, look who you\'ve collected!\n\n"
               f"✨ Name: <b>{w.name}</b>\n🏅 Rarity: <b>{spawns.rarity_label(w.rarity)}</b>\n"
               + (f"🏷️ Brand: <b>{w.brand}</b>\n" if w.brand else "")
               + (f"📦 Duplicate! You now own <b>{qty}</b>\n" if qty > 1 else "")
               + (f"💰 <b>+{coins}</b> coins\n" if coins else "")
               + (gain_line + "\n" if gain_line else "")
               + "\nView your wrestlers with /mycollection")
    kb = M(inline_keyboard=[[B(text=f"🗃️ {who.first_name}\'s Collection", callback_data=f"wc:c:{who.id}:0")]])
    await message.reply_photo(await spawns.media_for(w), caption=caption, reply_markup=kb)


@router.message(Command("collect"))
async def cmd_collect(message: Message, command: CommandObject) -> None:
    """Optional: the name can also just be typed in the chat; /collect gives feedback on a wrong guess."""
    if message.chat.type == "private" or not message.from_user:
        await message.answer("Collect wrestlers in a group: type the name when one appears.")
        return
    guess = (command.args or "").strip()
    if not guess:
        await message.reply("Just type the wrestler\'s name in the chat, e.g. <code>cena</code>.")
        return
    async with transaction() as s:
        status, w, qty = await spawns.claim(s, message.chat.id, message.from_user.id, guess)
        coins = economy.COLLECT_REWARD.get(w.rarity, 50) if status == "ok" else 0
        gain_line = ""
        if coins:
            await economy.add_coins(s, message.from_user.id, coins)
            gain_line = (await season_svc.on_event(s, message.from_user.id, "collect", season_svc.XP_COLLECT.get(w.rarity, 20))).line()
    if status == "none":
        await message.reply("No wrestler is waiting right now. Next one soon!")
    elif status == "late":
        await message.reply("⚡ Too late — someone already collected this one.")
    elif status == "wrong":
        await message.reply("❌ Wrong name, try again!")
    else:
        await _award(message, w, qty, coins, gain_line)


def _is_guess(message: Message) -> bool:
    """True only for a plain group message that is the right name of the wrestler waiting there (so nothing else is eaten)."""
    return bool(message.from_user and message.text and not message.text.startswith("/")
                and message.chat.type in ("group", "supergroup") and spawns.is_guess(message.chat.id, message.text))


@router.message(F.text, _is_guess)
async def on_guess(message: Message) -> None:
    async with transaction() as s:
        status, w, qty = await spawns.claim(s, message.chat.id, message.from_user.id, message.text)
        coins = economy.COLLECT_REWARD.get(w.rarity, 50) if status == "ok" else 0
        gain_line = ""
        if coins:
            await economy.add_coins(s, message.from_user.id, coins)
            gain_line = (await season_svc.on_event(s, message.from_user.id, "collect", season_svc.XP_COLLECT.get(w.rarity, 20))).line()
    if status == "ok":
        await _award(message, w, qty, coins, gain_line)


async def _collection_text(user_id: int, name: str, page: int) -> tuple[str, M | None]:
    async with transaction() as s:
        rows = await spawns.collection(s, user_id)
    if not rows:
        return f"🗃️ <b>{name}</b> has no wrestlers yet.", None
    pages = max(1, -(-len(rows) // PAGE))
    page = max(0, min(page, pages - 1))
    lines = [f"{spawns.rarity_label(w.rarity).split()[0]} {w.name}" + (f" ×{q}" if q > 1 else "")
             for w, q in rows[page * PAGE:(page + 1) * PAGE]]
    text = f"🗃️ <b>{name}\'s collection</b> — {len(rows)} wrestlers\n\n" + "\n".join(lines)
    nav = []
    if page > 0:
        nav.append(B(text="⬅️", callback_data=f"wc:c:{user_id}:{page - 1}"))
    if page < pages - 1:
        nav.append(B(text="➡️", callback_data=f"wc:c:{user_id}:{page + 1}"))
    return text, (M(inline_keyboard=[nav]) if nav else None)


@router.message(Command("mycollection"))
async def cmd_mycollection(message: Message) -> None:
    if not message.from_user:
        return
    text, kb = await _collection_text(message.from_user.id, message.from_user.first_name, 0)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("wc:"))
async def cb_collect(cb: CallbackQuery) -> None:
    parts = (cb.data or "").split(":")
    if len(parts) == 3 and parts[1] == "h" and parts[2].isdigit():
        async with transaction() as s:
            hint = await spawns.hint_for(s, int(parts[2]))
        await cb.answer(f"💡 {hint}" if hint else "This wrestler is gone.", show_alert=True)
    elif len(parts) == 4 and parts[1] == "c" and parts[2].isdigit() and parts[3].isdigit():
        uid = int(parts[2])
        name = cb.from_user.first_name if uid == cb.from_user.id else "Collection"
        text, kb = await _collection_text(uid, name, int(parts[3]))
        await cb.answer()
        if int(parts[3]) == 0 and cb.message.photo:                  # from the "collected!" card: send a new message
            await cb.message.answer(text, reply_markup=kb)
        else:
            await cb.message.edit_text(text, reply_markup=kb)
    else:
        await cb.answer()


# --------------------------------------------------------------------------------------------- owner

@router.message(F.photo & F.caption.regexp(r"^/addwrestler"))
async def cmd_addwrestler(message: Message) -> None:
    """Send a photo with caption:  /addwrestler John Cena | rare | RAW"""
    if not _owner(message):
        return
    body = re.sub(r"^/addwrestler(@\w+)?\s*", "", message.caption or "")
    parts = [p.strip() for p in body.split("|")]
    if not parts[0]:
        await message.reply("Caption format: <code>/addwrestler John Cena | rare | RAW</code>\n"
                            f"Rarities: {', '.join(spawns.RARITY)} (default common). Brand is optional.")
        return
    rarity = (parts[1].lower() if len(parts) > 1 and parts[1] else "common")
    if rarity not in spawns.RARITY:
        await message.reply(f"Unknown rarity. Use: {', '.join(spawns.RARITY)}")
        return
    brand = parts[2] if len(parts) > 2 and parts[2] else None
    async with transaction() as s:
        row = await spawns.add_wrestler(s, parts[0], rarity, brand, message.photo[-1].file_id)
    await message.reply(f"✅ Added <b>{row.name}</b> — {spawns.rarity_label(rarity)}" + (f" • {brand}" if brand else ""))


@router.message(Command("delwrestler"))
async def cmd_delwrestler(message: Message, command: CommandObject) -> None:
    if not _owner(message):
        return
    async with transaction() as s:
        n = await spawns.delete_wrestler(s, command.args or "")
    await message.answer(f"🗑️ Removed {n} wrestler card(s) from spawning." if n else "No wrestler with that name.")


@router.message(Command("wrestlers"))
async def cmd_wrestlers(message: Message) -> None:
    if not _owner(message):
        return
    async with transaction() as s:
        rows = (await s.execute(select(Wrestler.rarity, func.count()).where(Wrestler.active.is_(True)).group_by(Wrestler.rarity))).all()
    body = "\n".join(f"{spawns.rarity_label(r)}: {n}" for r, n in rows) or "none yet"
    await message.answer(f"🤼 <b>Wrestler cards</b>\n{body}")


@router.message(Command("spawn"))
async def cmd_spawn(message: Message, command: CommandObject) -> None:
    if not _owner(message):
        return
    if message.chat.type == "private":
        await message.answer("Use /spawn inside the group.")
        return
    args = (command.args or "").split()
    if not args or args[0] not in ("on", "off"):
        await message.answer("Use <code>/spawn on [minutes]</code> or <code>/spawn off</code> (default 30 minutes).")
        return
    minutes = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
    async with transaction() as s:
        row = await spawns.set_group(s, message.chat.id, args[0] == "on", minutes)
    await message.answer(f"✅ A wrestler will appear here every {row.interval_min} minutes." if row.enabled else "🛑 Spawning stopped here.")


@router.message(Command("spawnnow"))
async def cmd_spawnnow(message: Message, bot: Bot) -> None:
    if not _owner(message) or message.chat.type == "private":
        return
    if not await spawns.spawn(bot, message.chat.id):
        await message.answer("No wrestler cards yet. Send a photo with <code>/addwrestler Name | rarity | brand</code> in my DM.")
