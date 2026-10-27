"""/daily, /balance, /shop (one-message VIP skin shop with preview, buy and equip), /skin (your skins) and the owner's /givecoins.

The shop and skin menus are a single photo message that is edited in place: catalog page -> preview on YOUR card -> buy / equip.
Every button carries the id of the user who opened the menu, so nobody can press somebody else's buttons.
"""
import asyncio

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton as B, InlineKeyboardMarkup as M,
                           InputMediaPhoto, Message)

from config import get_settings
from database import transaction
from services import economy, moderation, mycard, shop_view
from services import season as season_svc
from services.cards import VIP_STYLES

router = Router(name="shop")


# ------------------------------------------------------------------------------------------ daily / balance

@router.message(Command("daily"))
async def cmd_daily(message: Message) -> None:
    if not message.from_user:
        return
    async with transaction() as s:
        res = await economy.claim_daily(s, message.from_user.id)
        gain = await season_svc.on_event(s, message.from_user.id, "daily", season_svc.XP_DAILY) if res else None
    if res is None:
        await message.reply("🎁 You already took today\'s reward. Come back tomorrow!")
        return
    reward, streak, balance = res
    await message.reply(f"🎁 <b>Daily reward: +{reward} coins</b>\n🔥 Streak: {streak} day{'s' if streak != 1 else ''} "
                        f"(a longer streak pays more)\n💰 Balance: <b>{balance}</b>" + (f"\n{gain.line()}" if gain and gain.line() else ""))


@router.message(Command("balance", "coins"))
async def cmd_balance(message: Message) -> None:
    if not message.from_user:
        return
    async with transaction() as s:
        coins = (await economy.wallet(s, message.from_user.id)).coins
    await message.reply(f"💰 You have <b>{coins}</b> coins.\nEarn them with /daily, by collecting wrestlers and winning matches. Spend them in /shop.")


# --------------------------------------------------------------------------------------------- helpers

def _nm(key: str) -> str:
    return f"{shop_view.EMOJI.get(key, '🎨')} {economy.skin_name(key)}"


async def _state(uid: int) -> tuple[int, set[str], str | None]:
    async with transaction() as s:
        coins = (await economy.wallet(s, uid)).coins
        return coins, await economy.owned_skins(s, uid), await economy.equipped_skin(s, uid)


async def _card(bot: Bot, user, skin: str | None) -> bytes:
    return await mycard.render(bot, user.id, user.full_name, user.username, skin=skin)


def _media(data: bytes, caption: str) -> InputMediaPhoto:
    return InputMediaPhoto(media=BufferedInputFile(data, "view.jpg"), caption=caption)


async def _show(bot: Bot, source, data: bytes, caption: str, kb: M) -> None:
    """Command -> new photo message; button -> edit the same message in place."""
    if isinstance(source, Message):
        await bot.send_photo(source.chat.id, BufferedInputFile(data, "view.jpg"), caption=caption, reply_markup=kb)
        return
    try:
        await source.message.edit_media(_media(data, caption), reply_markup=kb)
    except TelegramBadRequest as exc:
        if "not modified" not in str(exc).lower():
            await bot.send_photo(source.message.chat.id, BufferedInputFile(data, "view.jpg"), caption=caption, reply_markup=kb)


# --------------------------------------------------------------------------------------------- shop views

async def _shop_page(uid: int, page: int) -> tuple[bytes, str, M]:
    page = max(0, min(page, shop_view.pages() - 1))
    coins, owned, _ = await _state(uid)
    data = await asyncio.to_thread(shop_view.catalog_page, page)
    rows, line = [], []
    for key in shop_view.page_keys(page):
        label = f"{'✅' if key in owned else shop_view.EMOJI.get(key, '🎨')} {economy.skin_name(key)} · {economy.skin_price(key)}"
        line.append(B(text=label, callback_data=f"sh:v:{key}:{uid}"))
        if len(line) == 2:
            rows.append(line)
            line = []
    if line:
        rows.append(line)
    pages = shop_view.pages()
    rows.append([B(text="⬅️", callback_data=f"sh:p:{(page - 1) % pages}:{uid}"), B(text=f"{page + 1}/{pages}", callback_data=f"sh:n:{uid}"),
                 B(text="➡️", callback_data=f"sh:p:{(page + 1) % pages}:{uid}")])
    rows.append([B(text="🎨 My skins", callback_data=f"sh:m:{uid}"), B(text=f"💰 {coins}", callback_data=f"sh:c:{uid}")])
    rows.append([B(text="🎫 Season Pass", callback_data=f"sp:o:{uid}")])
    return data, f"🛒 <b>VIP Card Shop</b>\n💰 Your coins: <b>{coins}</b>\nTap a skin to preview it on <b>your own</b> card.", M(inline_keyboard=rows)


async def _preview(bot: Bot, user, key: str) -> tuple[bytes, str, M]:
    coins, owned, equipped = await _state(user.id)
    data = await _card(bot, user, key)
    uid, price = user.id, economy.skin_price(key)
    if key == equipped:
        action = B(text="🔘 Equipped", callback_data=f"sh:n:{uid}")
    elif key in owned:
        action = B(text="✅ Equip", callback_data=f"sh:e:{key}:{uid}")
    else:
        action = B(text=f"🛒 Buy · {price}", callback_data=f"sh:b:{key}:{uid}")
    kb = M(inline_keyboard=[[action], [B(text="⬅️ Back to shop", callback_data=f"sh:p:{shop_view.page_of(key)}:{uid}"),
                                       B(text="🎨 My skins", callback_data=f"sh:m:{uid}")]])
    status = "✅ You own this skin" if key in owned else ("💰 Enough coins to buy" if coins >= price else f"🔒 You need {price - coins} more coins")
    return data, f"✨ <b>{_nm(key)}</b> — {price} coins\n{status}\n💰 Balance: {coins}", kb


async def _my_skins(bot: Bot, user, skin: str | None = None) -> tuple[bytes, str, M]:
    coins, owned, equipped = await _state(user.id)
    data = await _card(bot, user, skin)
    uid = user.id
    current = equipped if skin is None else (None if skin == "default" else skin)
    rows = [[B(text=f"{'🔘' if key == current else '⚪'} {_nm(key)}", callback_data=f"sk:{key}:{uid}")] for key in VIP_STYLES if key in owned]
    rows.append([B(text=f"{'🔘' if current is None else '⚪'} 🪪 Default theme", callback_data=f"sk:default:{uid}")])
    rows.append([B(text="🛒 Open shop", callback_data=f"sh:p:0:{uid}")])
    now = _nm(current) if current else "Default theme"
    return data, f"🎨 <b>Your card skins</b>\nEquipped: <b>{now}</b>\nOwned: {len(owned - {economy.OWNER_SKIN})} / {len(shop_view.KEYS)} • 💰 {coins}\nTap a skin to wear it.", M(inline_keyboard=rows)


@router.message(Command("shop"))
async def cmd_shop(message: Message, bot: Bot) -> None:
    if message.from_user:
        data, caption, kb = await _shop_page(message.from_user.id, 0)
        await _show(bot, message, data, caption, kb)


@router.message(Command("skin"))
async def cmd_skin(message: Message, bot: Bot) -> None:
    if message.from_user:
        data, caption, kb = await _my_skins(bot, message.from_user)
        await _show(bot, message, data, caption, kb)


@router.callback_query(F.data.startswith("sh:"))
async def cb_shop(cb: CallbackQuery, bot: Bot) -> None:
    parts = (cb.data or "").split(":")
    if not parts[-1].lstrip("-").isdigit():
        await cb.answer("This menu is old — send /shop again.", show_alert=True)
        return
    owner = int(parts[-1])
    if cb.from_user.id != owner:
        await cb.answer("This is someone else\'s menu — send /shop for your own.", show_alert=True)
        return
    action, user = parts[1], cb.from_user
    if action == "n":
        await cb.answer()
    elif action == "c":
        coins, _, _ = await _state(owner)
        await cb.answer(f"💰 You have {coins} coins.\nEarn more: /daily, collecting wrestlers, winning matches.", show_alert=True)
    elif action == "p" and len(parts) == 4 and parts[2].isdigit():
        await cb.answer()
        await _show(bot, cb, *await _shop_page(owner, int(parts[2])))
    elif action == "v" and len(parts) == 4 and parts[2] in shop_view.KEYS:
        await cb.answer("🎨 Drawing your preview…")
        await _show(bot, cb, *await _preview(bot, user, parts[2]))
    elif action == "m":
        await cb.answer()
        await _show(bot, cb, *await _my_skins(bot, user))
    elif action == "b" and len(parts) == 4:
        async with transaction() as s:
            result = await economy.buy_skin(s, owner, parts[2])
            coins = (await economy.wallet(s, owner)).coins
        if result == "ok":
            await cb.answer("🎉 Purchased and equipped!", show_alert=True)
            await _show(bot, cb, *await _preview(bot, user, parts[2]))
        elif result == "owned":
            await cb.answer("You already own this skin.", show_alert=True)
        elif result == "poor":
            await cb.answer(f"Not enough coins. You have {coins}, it costs {economy.skin_price(parts[2])}.", show_alert=True)
        else:
            await cb.answer()
    elif action == "e" and len(parts) == 4:
        async with transaction() as s:
            ok = await economy.equip(s, owner, parts[2])
        await cb.answer("✅ Equipped!" if ok else "You don\'t own this skin.", show_alert=not ok)
        if ok:
            await _show(bot, cb, *await _preview(bot, user, parts[2]))
    else:
        await cb.answer()


@router.callback_query(F.data.startswith("sk:"))
async def cb_skin(cb: CallbackQuery, bot: Bot) -> None:
    parts = (cb.data or "").split(":")
    if len(parts) != 3 or not parts[2].lstrip("-").isdigit():
        await cb.answer("This menu is old — send /skin again.", show_alert=True)
        return
    if cb.from_user.id != int(parts[2]):
        await cb.answer("This is someone else\'s menu — send /skin for your own.", show_alert=True)
        return
    key = parts[1]
    async with transaction() as s:
        ok = await economy.equip(s, cb.from_user.id, None if key == "default" else key)
    if not ok:
        await cb.answer("You don\'t own this skin.", show_alert=True)
        return
    await cb.answer("✅ Equipped!")
    await _show(bot, cb, *await _my_skins(bot, cb.from_user, skin=key if key == "default" else None))


@router.message(Command("givecoins"))
async def cmd_givecoins(message: Message, command: CommandObject) -> None:
    if not message.from_user or message.from_user.id != get_settings().owner_id:
        return
    args = (command.args or "").split()
    if not args or not args[0].lstrip("-").isdigit():
        await message.answer("Use <code>/givecoins 500</code> as a reply, or <code>/givecoins 500 user_id</code>.")
        return
    amount = int(args[0])
    target = int(args[1]) if len(args) > 1 and args[1].isdigit() else (
        message.reply_to_message.from_user.id if message.reply_to_message and message.reply_to_message.from_user else None)
    if target is None:
        await message.answer("Reply to the player or give his user id.")
        return
    async with transaction() as s:
        balance = await economy.add_coins(s, target, amount)
        await moderation.audit(s, message.from_user.id, "givecoins", target, f"{amount:+d} -> {balance}")
    await message.answer(f"✅ {amount:+d} coins for <code>{target}</code>. Balance: {balance}")
