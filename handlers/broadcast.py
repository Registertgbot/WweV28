"""Owner broadcast suite. Reply to ANY message (text, photo+caption, video, GIF, document, sticker, voice, poll, album) and use:

  /broadcast  [target] [options]   exact copy, no sender shown          /fbroadcast [target] [options]   real forward ("Forwarded from")
  /pbroadcast [target] [options]   personal text with {name} {coins} {cards} {belts}      /pollbroadcast  Question | A | *B | C
Without a reply, the text after the options is sent.  /bhelp shows everything, /broadcasts + /bcancel manage scheduled ones,
/bcstats shows statistics.  Options: pin silent at=9:30pm in=45m repeat=daily|weekly reward=500 and btn: Label|https://link lines.
"""
import asyncio
import html
import json
import logging
import secrets
import time
from collections import Counter
from datetime import timedelta

from aiogram import Bot, F, Router
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton as B, InlineKeyboardMarkup as M, Message
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from config import get_settings
from database import transaction
from models import (AllowedGroup, BroadcastJob, BroadcastRun, Championship, RewardClaim, RewardDrop, User, UserSkin, Wallet,
                    WrestlerOwned, utcnow)
from services import economy, moderation, titles
from services import tour_rules as tr
from services.broadcast_parse import dumps, parse_command, parse_poll

router = Router(name="broadcast")
log = logging.getLogger(__name__)
_pending: dict[str, dict] = {}
ALBUMS: dict[tuple[int, str], list[int]] = {}
PENDING_TTL, SEND_GAP, DROP_HOURS, LOOP_SECONDS = 600, 0.06, 24, 20
STEP = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}


def _owner(user_id: int | None) -> bool:
    return bool(user_id) and user_id == get_settings().owner_id


class AlbumTracker(BaseMiddleware):
    """Remembers the message ids of albums the owner sends, so one reply can broadcast the whole album."""

    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.media_group_id and event.from_user and _owner(event.from_user.id):
            ids = ALBUMS.setdefault((event.chat.id, event.media_group_id), [])
            if event.message_id not in ids:
                ids.append(event.message_id)
            while len(ALBUMS) > 200:
                ALBUMS.pop(next(iter(ALBUMS)))
        return await handler(event, data)


# ------------------------------------------------------------------------------------------ audience

async def _dm_ready(s, ids) -> list[int]:
    ids = list(set(ids))
    return list((await s.execute(select(User.id).where(User.id.in_(ids), User.dm_started.is_(True)))).scalars().all()) if ids else []


async def recipients(kind: str) -> list[int]:
    out: list[int] = []
    async with transaction() as s:
        if kind.startswith("chat:"):
            out = [int(kind[5:])] if kind[5:].lstrip("-").isdigit() else []
        elif kind.startswith("ids:"):
            out = [int(x) for x in kind[4:].split(",") if x.strip().lstrip("-").isdigit()]
        else:
            if kind in ("groups", "all"):
                out += list((await s.execute(select(AllowedGroup.chat_id))).scalars().all()) + list(get_settings().default_groups)
            if kind in ("users", "all"):
                out += list((await s.execute(select(User.id).where(User.dm_started.is_(True)))).scalars().all())
            if kind == "vip":
                out += await _dm_ready(s, (await s.execute(select(UserSkin.user_id).distinct())).scalars().all())
            if kind == "collectors":
                out += await _dm_ready(s, (await s.execute(select(WrestlerOwned.user_id).distinct())).scalars().all())
            if kind == "champions":
                held = [h for row in (await s.execute(select(Championship))).scalars().all() for h in titles.holders(row)]
                out += await _dm_ready(s, held)
            if kind == "players":
                out += list((await s.execute(select(User.id).where(User.dm_started.is_(True), User.total_matches > 0))).scalars().all())
    seen: set[int] = set()
    return [i for i in out if not (i in seen or seen.add(i))]


# ---------------------------------------------------------------------------------------- delivering

def _kb(buttons_json: str | None, extra: list | None = None) -> M | None:
    rows = [[B(text=label, url=url) for label, url in row] for row in (json.loads(buttons_json) if buttons_json else [])]
    rows += extra or []
    return M(inline_keyboard=rows) if rows else None


async def _personal(text: str, user_id: int) -> str:
    if user_id < 0:
        values = {"name": "everyone", "coins": "", "cards": "", "belts": ""}
    else:
        async with transaction() as s:
            user, wallet = await s.get(User, user_id), await s.get(Wallet, user_id)
            cards = (await s.execute(select(func.count()).select_from(WrestlerOwned).where(WrestlerOwned.user_id == user_id))).scalar_one()
            belts = len(await titles.belts_of(s, user_id))
        values = {"name": html.escape(user.display_name) if user else "champ", "coins": wallet.coins if wallet else 0,
                  "cards": cards, "belts": belts}
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


async def _deliver(bot: Bot, j: dict, chat_id: int, kb: M | None) -> int:
    quiet = bool(j["silent"])
    ids = [int(x) for x in (j["src_ids"] or "").split(",") if x]
    for attempt in (0, 1):
        try:
            if j["mode"] == "copy":
                if len(ids) > 1:                                        # an album stays an album
                    return (await bot.copy_messages(chat_id, j["src_chat"], ids, disable_notification=quiet))[0].message_id
                return (await bot.copy_message(chat_id, j["src_chat"], ids[0], reply_markup=kb, disable_notification=quiet)).message_id
            if j["mode"] == "forward":
                if len(ids) > 1:
                    return (await bot.forward_messages(chat_id, j["src_chat"], ids, disable_notification=quiet))[0].message_id
                return (await bot.forward_message(chat_id, j["src_chat"], ids[0], disable_notification=quiet)).message_id
            if j["mode"] == "poll":
                poll = json.loads(j["text"])
                extra = {"type": "quiz", "correct_option_id": poll["correct"]} if poll["correct"] is not None else {}
                return (await bot.send_poll(chat_id, poll["q"], poll["options"], is_anonymous=True, disable_notification=quiet, **extra)).message_id
            text = await _personal(j["text"], chat_id) if j["personalize"] else j["text"]
            return (await bot.send_message(chat_id, text, reply_markup=kb, disable_notification=quiet)).message_id
        except TelegramRetryAfter as exc:
            if attempt:
                raise
            await asyncio.sleep(exc.retry_after + 1)
    raise RuntimeError("unreachable")


async def _execute(bot: Bot, job_id: int, status: Message | None = None) -> None:
    async with transaction() as s:
        job = await s.get(BroadcastJob, job_id)
        if job is None or job.status not in ("pending", "running"):
            return
        job.status = "running"
        j = {c.name: getattr(job, c.name) for c in BroadcastJob.__table__.columns}
    targets = await recipients(j["kind"])
    kb, drop_id = _kb(j["buttons"]), None
    if j["reward"] and any(t < 0 for t in targets):
        async with transaction() as s:
            drop = RewardDrop(coins=j["reward"], expires_at=utcnow() + timedelta(hours=DROP_HOURS))
            s.add(drop)
            await s.flush()
            drop_id = drop.id
    sent, failed, reward_total, started = 0, Counter(), 0, time.monotonic()
    for i, chat_id in enumerate(targets, start=1):
        try:
            mid = await _deliver(bot, j, chat_id, kb)
            sent += 1
            if j["pin"] and chat_id < 0:
                try:
                    await bot.pin_chat_message(chat_id, mid, disable_notification=True)
                except TelegramAPIError:
                    failed["pin failed"] += 1
            if j["reward"]:
                if chat_id > 0:
                    async with transaction() as s:
                        await economy.add_coins(s, chat_id, j["reward"])
                    reward_total += j["reward"]
                    await bot.send_message(chat_id, f"🎁 <b>Reward!</b> +{j['reward']} coins were added to your wallet.")
                elif drop_id:
                    await bot.send_message(chat_id, f"🎁 <b>Reward drop</b> — everyone can claim <b>{j['reward']}</b> coins, once!",
                                           reply_markup=M(inline_keyboard=[[B(text=f"🎁 Claim {j['reward']} coins", callback_data=f"rw:{drop_id}")]]))
        except TelegramAPIError as exc:
            failed[type(exc).__name__] += 1
        except Exception:
            log.exception("Broadcast to %s failed", chat_id)
            failed["error"] += 1
        if status is not None and i % 20 == 0:
            try:
                await status.edit_text(f"📣 Sending… {i}/{len(targets)}")
            except TelegramAPIError:
                pass
        await asyncio.sleep(SEND_GAP)
    problems = ", ".join(f"{n}×{c}" for n, c in failed.most_common(4))
    now = utcnow()
    async with transaction() as s:
        s.add(BroadcastRun(job_id=job_id, mode=j["mode"], kind=j["kind"][:120], total=len(targets), sent=sent,
                           failed=len(targets) - sent, reward_total=reward_total, problems=problems[:300] or None))
        job = await s.get(BroadcastJob, job_id)
        if job.repeat and job.status != "cancelled":
            job.run_at = job.run_at + STEP[job.repeat]
            while job.run_at <= now:
                job.run_at += STEP[job.repeat]
            job.status = "pending"
        elif job.status != "cancelled":
            job.status = "done"
        await moderation.audit(s, j["owner_id"], "broadcast", None, f"#{job_id} {j['mode']} {j['kind']} sent {sent}/{len(targets)}")
    report = (f"✅ <b>Broadcast #{job_id} finished</b> in {int(time.monotonic() - started)}s\nDelivered: <b>{sent}</b> / {len(targets)}"
              + (f"\n🎁 Coins given: {reward_total}" if reward_total else "") + (f"\nProblems: {problems}" if problems else ""))
    try:
        if status is not None:
            await status.edit_text(report)
        else:
            await bot.send_message(j["owner_id"], report)
    except TelegramAPIError:
        pass


async def deadline_loop(bot: Bot) -> None:
    """Starts scheduled / repeating broadcasts when they are due."""
    while True:
        try:
            async with transaction() as s:
                due = list((await s.execute(select(BroadcastJob.id).where(BroadcastJob.status == "pending",
                                                                         BroadcastJob.run_at <= utcnow()))).scalars().all())
            for job_id in due:
                asyncio.create_task(_execute(bot, job_id))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Broadcast loop error")
        await asyncio.sleep(LOOP_SECONDS)


# ------------------------------------------------------------------------------------------ commands

async def _start(message: Message, command: CommandObject, mode: str, default_kind: str = "all", personal: bool = False) -> None:
    if not _owner(message.from_user.id if message.from_user else None):
        return
    p = parse_command(command.args, default_kind)
    if p["error"]:
        await message.answer("⚠️ " + p["error"])
        return
    src, ids, poll, text = message.reply_to_message, [], None, p["text"]
    if mode == "poll":
        poll = parse_poll(text)
        if poll is None:
            await message.answer("Use <code>/pollbroadcast [target]</code> then <code>Question | Option A | *Correct | Option C</code> "
                                 "(2 to 10 options; a * marks the right answer and makes it a quiz).")
            return
        text = dumps(poll)
    elif personal:
        if not text:
            await message.answer("Write the text after the options: <code>/pbroadcast users Hi {name}, you have {coins} coins!</code>")
            return
        mode = "text"
    elif src is None:
        if mode == "forward" or not text:
            await message.answer("Reply to the message you want to send (see /bhelp), or write the text after the options.")
            return
        mode = "text"
    else:
        ids = ALBUMS.get((src.chat.id, src.media_group_id), [src.message_id]) if src.media_group_id else [src.message_id]
        ids = sorted(ids)
    when, now = utcnow(), utcnow()
    if p["at"]:
        when = tr.parse_ist(p["at"], now)
        if when is None:
            await message.answer("I could not read that time. Try <code>at=9:30pm</code>, <code>at=tomorrow_8pm</code> or <code>in=45m</code>.")
            return
    targets = await recipients(p["kind"])
    if not targets:
        await message.answer("There is nobody to send to for that target.")
        return
    for key in [k for k, v in _pending.items() if time.monotonic() - v["mono"] > PENDING_TTL]:
        _pending.pop(key, None)
    token = secrets.token_hex(3)
    _pending[token] = {"mono": time.monotonic(), "owner": message.from_user.id, "mode": mode, "kind": p["kind"], "pin": p["pin"],
                       "silent": p["silent"], "personalize": personal, "reward": p["reward"], "text": text or None,
                       "buttons": dumps(p["buttons"]) if p["buttons"] else None, "src_chat": src.chat.id if src else None,
                       "src_ids": ",".join(map(str, ids)) or None, "run_at": when, "repeat": p["repeat"]}
    label = {"copy": "exact copy" + (f" (album of {len(ids)})" if len(ids) > 1 else ""), "forward": "forward (shows “Forwarded from”)",
             "text": "personal text" if personal else "text message", "poll": "poll" + (" (quiz)" if poll and poll["correct"] is not None else "")}[mode]
    notes = []
    if p["buttons"] and (mode == "forward" or len(ids) > 1):
        notes.append("⚠️ Buttons cannot be added to forwards or albums — they will be ignored.")
    if p["buttons"] and mode == "poll":
        notes.append("⚠️ Polls cannot carry buttons.")
    if when > now + timedelta(seconds=30):
        notes.append(f"⏰ Scheduled for <b>{tr.fmt_ist(when)}</b>" + (f", repeating <b>{p['repeat']}</b>" if p["repeat"] else "")
                     + (" — keep the source message in this chat until then." if src else ""))
    lines = [f"📣 <b>Broadcast preview</b>", f"Type: {label}", f"To: <b>{p['kind']}</b> — {len(targets)} chats"]
    lines += ([f"🎁 Reward: {p['reward']} coins each"] if p["reward"] else []) + (["🔕 Silent"] if p["silent"] else []) + (["📌 Pinned in groups"] if p["pin"] else [])
    await message.reply("\n".join(lines + notes + ["", "Send it?"]),
                        reply_markup=M(inline_keyboard=[[B(text="✅ Confirm", callback_data=f"bc:go:{token}"),
                                                         B(text="❌ Cancel", callback_data=f"bc:x:{token}")]]))


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, command: CommandObject) -> None:
    await _start(message, command, "copy")


@router.message(Command("fbroadcast"))
async def cmd_fbroadcast(message: Message, command: CommandObject) -> None:
    await _start(message, command, "forward")


@router.message(Command("pbroadcast"))
async def cmd_pbroadcast(message: Message, command: CommandObject) -> None:
    await _start(message, command, "text", default_kind="users", personal=True)


@router.message(Command("pollbroadcast"))
async def cmd_pollbroadcast(message: Message, command: CommandObject) -> None:
    await _start(message, command, "poll")


@router.callback_query(F.data.startswith("bc:"))
async def cb_broadcast(cb: CallbackQuery, bot: Bot) -> None:
    if not _owner(cb.from_user.id):
        await cb.answer("Owner only.", show_alert=True)
        return
    _, action, token = (cb.data or "bc::").split(":", 2)
    job = _pending.pop(token, None)
    if job is None:
        await cb.answer("This preview expired. Send the command again.", show_alert=True)
        return
    if action == "x":
        await cb.answer("Cancelled.")
        await cb.message.edit_text("❌ Broadcast cancelled.")
        return
    later = job["run_at"] > utcnow() + timedelta(seconds=30)
    async with transaction() as s:
        row = BroadcastJob(owner_id=job["owner"], mode=job["mode"], kind=job["kind"][:120], pin=job["pin"], silent=job["silent"],
                           personalize=job["personalize"], reward=job["reward"], text=job["text"], buttons=job["buttons"],
                           src_chat=job["src_chat"], src_ids=job["src_ids"], run_at=job["run_at"] if later else utcnow(),
                           repeat=job["repeat"], status="pending" if later else "running")
        s.add(row)
        await s.flush()
        job_id = row.id
    if later:
        await cb.answer("Scheduled.")
        await cb.message.edit_text(f"⏰ Broadcast <b>#{job_id}</b> scheduled for {tr.fmt_ist(job['run_at'])}"
                                   + (f" (repeats {job['repeat']})" if job["repeat"] else "") + f".\nCancel it with /bcancel {job_id}")
        return
    await cb.answer("Sending…")
    await cb.message.edit_text("📣 Sending…")
    asyncio.create_task(_execute(bot, job_id, cb.message))


@router.message(Command("broadcasts"))
async def cmd_broadcasts(message: Message) -> None:
    if not _owner(message.from_user.id if message.from_user else None):
        return
    async with transaction() as s:
        rows = (await s.execute(select(BroadcastJob).where(BroadcastJob.status == "pending").order_by(BroadcastJob.run_at))).scalars().all()
    lines = [f"#{r.id} • {tr.fmt_ist(r.run_at)} • {r.mode} → {r.kind}" + (f" • repeats {r.repeat}" if r.repeat else "") for r in rows]
    await message.answer("⏰ <b>Scheduled broadcasts</b>\n" + ("\n".join(lines) or "none") + ("\n\nCancel: /bcancel &lt;id&gt;" if rows else ""))


@router.message(Command("bcancel"))
async def cmd_bcancel(message: Message, command: CommandObject) -> None:
    if not _owner(message.from_user.id if message.from_user else None):
        return
    arg = (command.args or "").strip().lstrip("#")
    if not arg.isdigit():
        await message.answer("Use <code>/bcancel 3</code> (the number from /broadcasts).")
        return
    async with transaction() as s:
        job = await s.get(BroadcastJob, int(arg))
        ok = job is not None and job.status in ("pending", "running")
        if ok:
            job.status = "cancelled"
    await message.answer("🛑 Broadcast cancelled." if ok else "No open broadcast with that number.")


@router.message(Command("bcstats"))
async def cmd_bcstats(message: Message) -> None:
    if not _owner(message.from_user.id if message.from_user else None):
        return
    async with transaction() as s:
        runs, sent, failed, coins = (await s.execute(select(func.count(), func.coalesce(func.sum(BroadcastRun.sent), 0),
                                                           func.coalesce(func.sum(BroadcastRun.failed), 0),
                                                           func.coalesce(func.sum(BroadcastRun.reward_total), 0)))).one()
        last = (await s.execute(select(BroadcastRun).order_by(BroadcastRun.id.desc()).limit(8))).scalars().all()
        groups, users = len(await recipients("groups")), len(await recipients("users"))
        pending = (await s.execute(select(func.count()).select_from(BroadcastJob).where(BroadcastJob.status == "pending"))).scalar_one()
    rate = f"{100 * sent // max(1, sent + failed)}%"
    lines = [f"#{r.job_id or '-'} • {tr.fmt_ist(r.at)} • {r.mode}→{r.kind} • {r.sent}/{r.total}" + (f" ⚠️{r.failed}" if r.failed else "") for r in last]
    await message.answer(f"📊 <b>Broadcast statistics</b>\nRuns: {runs} • Delivered: {sent} • Failed: {failed} • Success rate: {rate}\n"
                         f"🎁 Reward coins given: {coins}\nAudience now: {groups} groups, {users} users (DM open)\nScheduled: {pending}\n\n"
                         "<b>Last runs</b>\n" + ("\n".join(lines) or "none yet"))


@router.message(Command("bhelp"))
async def cmd_bhelp(message: Message) -> None:
    if not _owner(message.from_user.id if message.from_user else None):
        return
    await message.answer(
        "📣 <b>Broadcast help</b>\n\n"
        "<b>Reply to any message</b> (text, photo+caption, video, GIF, file, sticker, voice, poll, album):\n"
        "• <code>/broadcast</code> — exact copy, no sender shown\n• <code>/fbroadcast</code> — forward, shows “Forwarded from”\n\n"
        "<b>Write the text yourself</b> (no reply):\n• <code>/broadcast groups Hello <b>all</b></code>\n"
        "• <code>/pbroadcast users Hi {name}! You have {coins} coins</code> (also {cards} {belts})\n"
        "• <code>/pollbroadcast groups</code> + new line <code>Who wins? | Cena | *Rock | Orton</code> (* = quiz answer)\n\n"
        "<b>Targets:</b> groups, users, all, vip, champions, collectors, players, chat:&lt;id&gt;, ids:1,2,3\n"
        "<b>Options</b> (first line): pin • silent • at=9:30pm • at=tomorrow_8pm • in=45m • repeat=daily|weekly • reward=500\n"
        "<b>Buttons</b> (extra lines): <code>btn: Join|https://t.me/x ; Rules|https://example.com</code>\n\n"
        "Example:\n<code>/broadcast groups pin silent at=9pm repeat=daily reward=200\nbtn: Join|https://t.me/x\nTournament tonight!</code>\n\n"
        "Manage: /broadcasts • /bcancel &lt;id&gt; • /bcstats")


@router.callback_query(F.data.startswith("rw:"))
async def cb_reward(cb: CallbackQuery) -> None:
    drop_id = int((cb.data or "rw:0").split(":")[1] or 0)
    try:
        async with transaction() as s:
            drop = await s.get(RewardDrop, drop_id)
            if drop is None or drop.expires_at <= utcnow():
                await cb.answer("This reward has expired.", show_alert=True)
                return
            if await s.get(RewardClaim, (drop_id, cb.from_user.id)) is not None:
                await cb.answer("You already claimed this one.", show_alert=True)
                return
            s.add(RewardClaim(drop_id=drop_id, user_id=cb.from_user.id))
            balance = await economy.add_coins(s, cb.from_user.id, drop.coins)
            coins = drop.coins
    except IntegrityError:
        await cb.answer("You already claimed this one.", show_alert=True)
        return
    await cb.answer(f"🎁 +{coins} coins! Balance: {balance}", show_alert=True)
