"""Season Pass: /pass (one photo message that you flip through), /missions, /passboard and the owner's season commands."""
import asyncio
import math

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton as B, InlineKeyboardMarkup as M, InputMediaPhoto,
                           Message)

from config import get_settings
from database import transaction
from models import utcnow
from services import avatars, economy, moderation, season as sn
from services import tour_rules as tr
from services.cards import Person
from services.pass_card import PER_PAGE, PassCard, render_pass

router = Router(name="season")


def _owner(message: Message) -> bool:
    return bool(message.from_user) and message.from_user.id == get_settings().owner_id


def _days_left(season) -> int:
    return max(-1, (season.ends_at - utcnow()).days)


# ----------------------------------------------------------------------------------------------- views

async def _pass_view(bot: Bot, user, page: int | None = None) -> tuple[bytes, str, M] | None:
    async with transaction() as s:
        v = await sn.view(s, user.id)
        coins = (await economy.wallet(s, user.id)).coins if v else 0
    if v is None:
        return None
    avatar = await avatars.fetch_avatar(bot, user.id)                     # network, outside the database transaction
    pages = math.ceil(v.season.max_level / PER_PAGE)
    page = max(0, min(page if page is not None else min(v.level // PER_PAGE, pages - 1), pages - 1))
    card = PassCard(person=Person(user.id, user.full_name, avatar), season_number=v.season.number, season_name=v.season.name, level=v.level,
                    into=v.into, size=v.size, xp=v.xp, max_level=v.season.max_level, premium=v.premium, price=v.season.premium_price, page=page,
                    claimed=v.claimed, waiting=len(v.waiting), rank=v.rank, days_left=_days_left(v.season),
                    reward=lambda lv, track: sn.reward(lv, track, v.season.max_level), skin_title=economy.skin_name)
    photo = await asyncio.to_thread(render_pass, card)
    uid = user.id
    rows = [[B(text="⬅️", callback_data=f"sp:p:{(page - 1) % pages}:{uid}"), B(text=f"Levels {page * PER_PAGE + 1}-{min(v.season.max_level, (page + 1) * PER_PAGE)}", callback_data=f"sp:n:{uid}"),
             B(text="➡️", callback_data=f"sp:p:{(page + 1) % pages}:{uid}")],
            [B(text=f"🎁 Claim all ({len(v.waiting)})" if v.waiting else "🎁 Nothing to claim yet", callback_data=f"sp:c:{page}:{uid}" if v.waiting else f"sp:n:{uid}")],
            [B(text="📋 Missions", callback_data=f"sp:m:{page}:{uid}"), B(text="🏆 Top 10", callback_data=f"sp:t:{page}:{uid}")]]
    rows.append([B(text="💎 Premium active", callback_data=f"sp:n:{uid}")] if v.premium else
                [B(text=f"💎 Get Premium · {v.season.premium_price}", callback_data=f"sp:b:{page}:{uid}")])
    caption = (f"🎫 <b>Season {v.season.number} — {v.season.name}</b>\n⭐ Level {v.level}/{v.season.max_level} • {v.xp} XP • 💰 {coins} coins\n"
               + ("💎 Premium track unlocked" if v.premium else "🔒 Premium track locked — unlock it to claim the gold rewards"))
    return photo, caption, M(inline_keyboard=rows)


def _bar(done: int, target: int) -> str:
    filled = round(8 * min(done, target) / target)
    return "▰" * filled + "▱" * (8 - filled)


async def _missions_caption(user_id: int) -> str:
    async with transaction() as s:
        daily, weekly = await sn.mission_rows(s, user_id)
    def block(title, rows):
        return f"<b>{title}</b>\n" + "\n".join(f"{'✅' if done else '▫️'} {m.title}  {_bar(p, m.target)} {p}/{m.target}  <i>+{m.xp} XP</i>" for m, p, done in rows)
    return "📋 <b>Missions</b>\n\n" + block("Daily (resets at midnight IST)", daily) + "\n\n" + block("Weekly (resets Monday)", weekly)


async def _top_caption(user_id: int) -> str:
    async with transaction() as s:
        season = await sn.pass_season(s)
        rows = await sn.leaderboard(s, season) if season else []
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    return "🏆 <b>Season leaderboard</b>\n\n" + ("\n".join(f"{medals[i]} <b>{name}</b> — Lv {level} • {xp} XP" for i, (_, name, xp, level) in enumerate(rows)) or "Nobody has earned XP yet.")


async def _send(bot: Bot, chat_id: int, user, page: int | None = None) -> None:
    view = await _pass_view(bot, user, page)
    if view is None:
        await bot.send_message(chat_id, "🎫 No season is running right now. The owner will start the next one soon!")
        return
    photo, caption, kb = view
    await bot.send_photo(chat_id, BufferedInputFile(photo, "pass.jpg"), caption=caption, reply_markup=kb)


async def _edit_view(bot: Bot, cb: CallbackQuery, page: int | None) -> None:
    view = await _pass_view(bot, cb.from_user, page)
    if view is None:
        await cb.answer("No season is running.", show_alert=True)
        return
    photo, caption, kb = view
    try:
        await cb.message.edit_media(InputMediaPhoto(media=BufferedInputFile(photo, "pass.jpg"), caption=caption), reply_markup=kb)
    except TelegramBadRequest as exc:
        if "not modified" not in str(exc).lower():
            await _send(bot, cb.message.chat.id, cb.from_user, page)


@router.message(Command("pass", "season"))
async def cmd_pass(message: Message, bot: Bot) -> None:
    if message.from_user:
        await _send(bot, message.chat.id, message.from_user)


@router.message(Command("missions"))
async def cmd_missions(message: Message, bot: Bot) -> None:
    if not message.from_user:
        return
    async with transaction() as s:
        running = await sn.current(s) is not None
    if not running:
        await message.answer("🎫 No season is running right now.")
        return
    await message.answer(await _missions_caption(message.from_user.id))


@router.message(Command("passboard"))
async def cmd_passboard(message: Message) -> None:
    await message.answer(await _top_caption(message.from_user.id if message.from_user else 0))


@router.callback_query(F.data.startswith("sp:"))
async def cb_pass(cb: CallbackQuery, bot: Bot) -> None:
    parts = (cb.data or "").split(":")
    if len(parts) < 3 or not parts[-1].lstrip("-").isdigit():
        await cb.answer("This menu is old — send /pass again.", show_alert=True)
        return
    if cb.from_user.id != int(parts[-1]):
        await cb.answer("This is someone else's pass — send /pass for yours.", show_alert=True)
        return
    action = parts[1]
    page = int(parts[2]) if len(parts) == 4 and parts[2].isdigit() else None
    if action == "n":
        await cb.answer()
    elif action == "o":
        await cb.answer()
        await _send(bot, cb.message.chat.id, cb.from_user)
    elif action == "p":
        await cb.answer()
        await _edit_view(bot, cb, page)
    elif action == "c":
        async with transaction() as s:
            lines = await sn.claim_all(s, cb.from_user.id)
        if not lines:
            await cb.answer("Nothing to claim.", show_alert=True)
            return
        await cb.answer("🎁 Claimed!")
        await cb.message.answer("🎁 <b>Season rewards claimed</b>\n" + "\n".join(lines[:25]) + (f"\n…and {len(lines) - 25} more" if len(lines) > 25 else ""))
        await _edit_view(bot, cb, page)
    elif action == "b":
        async with transaction() as s:
            result = await sn.buy_premium(s, cb.from_user.id)
            season = await sn.current(s)
            coins = (await economy.wallet(s, cb.from_user.id)).coins
        if result == "ok":
            await cb.answer("💎 Premium unlocked! Tap Claim all to collect the gold rewards.", show_alert=True)
            await _edit_view(bot, cb, page)
        elif result == "owned":
            await cb.answer("You already have Premium.", show_alert=True)
        elif result == "poor":
            await cb.answer(f"Not enough coins. You have {coins}, Premium costs {season.premium_price}.", show_alert=True)
        else:
            await cb.answer("No season is running.", show_alert=True)
    elif action in ("m", "t"):
        await cb.answer()
        caption = await (_missions_caption(cb.from_user.id) if action == "m" else _top_caption(cb.from_user.id))
        back = M(inline_keyboard=[[B(text="⬅️ Back to pass", callback_data=f"sp:p:{page if page is not None else 0}:{cb.from_user.id}")]])
        try:
            await cb.message.edit_caption(caption=caption, reply_markup=back)
        except TelegramBadRequest:
            await cb.message.answer(caption, reply_markup=back)
    else:
        await cb.answer()


# ------------------------------------------------------------------------------------------------ owner

@router.message(Command("seasonnew"))
async def cmd_seasonnew(message: Message, command: CommandObject) -> None:
    """/seasonnew 30 auto Golden Era   (days, optional `auto` = start the next season automatically, then the name)"""
    if not _owner(message):
        return
    args = (command.args or "").split()
    if not args or not args[0].isdigit():
        await message.answer("Use <code>/seasonnew 30 auto Golden Era</code> (30 days; <code>auto</code> starts the next season by itself).")
        return
    days, rest = int(args[0]), args[1:]
    auto = bool(rest) and rest[0].lower() == "auto"
    name = " ".join(rest[1:] if auto else rest) or "Season"
    async with transaction() as s:
        season = await sn.start_season(s, name, days, auto)
        if season is not None:
            await moderation.audit(s, message.from_user.id, "seasonnew", None, f"#{season.number} {season.name} {days}d")
    if season is None:
        await message.answer("A season is already running. End it first with /seasonend.")
        return
    await message.answer(f"🚀 <b>Season {season.number} — {season.name}</b> started for {days} days" + (" (auto-renew on)" if auto else "") +
                         f".\nPremium costs {season.premium_price} coins. Announce it with /broadcast!")


@router.message(Command("seasonend"))
async def cmd_seasonend(message: Message, bot: Bot) -> None:
    if not _owner(message):
        return
    async with transaction() as s:
        season = await sn.current(s)
        if season is None:
            await message.answer("No season is running.")
            return
        season.auto_renew = False
        text = await sn.end_season(s, season)
        groups = await sn._group_ids(s)
        await moderation.audit(s, message.from_user.id, "seasonend", None, f"#{season.number}")
    from services.tg import safe_send
    for chat_id in groups:
        await safe_send(bot, chat_id, text)
    await message.answer("🏁 Season ended, prizes paid.\n\n" + text)


@router.message(Command("seasoninfo"))
async def cmd_seasoninfo(message: Message) -> None:
    if not _owner(message):
        return
    async with transaction() as s:
        season = await sn.current(s)
        players = premium = 0
        if season:
            from sqlalchemy import func, select
            from models import SeasonPlayer
            players = (await s.execute(select(func.count()).select_from(SeasonPlayer).where(SeasonPlayer.season_id == season.id))).scalar_one()
            premium = (await s.execute(select(func.count()).select_from(SeasonPlayer).where(SeasonPlayer.season_id == season.id, SeasonPlayer.premium.is_(True)))).scalar_one()
    if season is None:
        await message.answer("No season is running. Start one: <code>/seasonnew 30 auto Name</code>")
        return
    await message.answer(f"🎫 <b>Season {season.number} — {season.name}</b>\nEnds: {tr.fmt_ist(season.ends_at)}\nLevels: {season.max_level} • Premium: {season.premium_price} coins\n"
                         f"Players: {players} • Premium owners: {premium}\nAuto-renew: {'on' if season.auto_renew else 'off'}")


@router.message(Command("givepass"))
async def cmd_givepass(message: Message, command: CommandObject) -> None:
    if not _owner(message):
        return
    arg = (command.args or "").strip()
    target = int(arg) if arg.lstrip("-").isdigit() else (message.reply_to_message.from_user.id if message.reply_to_message and message.reply_to_message.from_user else None)
    if target is None:
        await message.answer("Use <code>/givepass</code> as a reply, or <code>/givepass user_id</code>.")
        return
    async with transaction() as s:
        season = await sn.current(s)
        if season is None:
            await message.answer("No season is running.")
            return
        (await sn.player(s, season, target)).premium = True
        await moderation.audit(s, message.from_user.id, "givepass", target, f"season {season.number}")
    await message.answer(f"💎 Premium pass given to <code>{target}</code>.")


@router.message(Command("addxp"))
async def cmd_addxp(message: Message, command: CommandObject) -> None:
    if not _owner(message):
        return
    args = (command.args or "").split()
    if not args or not args[0].lstrip("-").isdigit():
        await message.answer("Use <code>/addxp 500</code> as a reply, or <code>/addxp 500 user_id</code>.")
        return
    target = int(args[1]) if len(args) > 1 and args[1].isdigit() else (message.reply_to_message.from_user.id if message.reply_to_message and message.reply_to_message.from_user else None)
    if target is None:
        await message.answer("Reply to the player or give his user id.")
        return
    async with transaction() as s:
        season = await sn.current(s)
        if season is None:
            await message.answer("No season is running.")
            return
        sp = await sn.player(s, season, target)
        sp.xp = max(0, sp.xp + int(args[0]))
        level = sn.level_for(sp.xp, season.max_level)
        await moderation.audit(s, message.from_user.id, "addxp", target, f"{args[0]} -> {sp.xp}")
    await message.answer(f"⭐ <code>{target}</code> now has {sp.xp} XP (Lv {level}).")
