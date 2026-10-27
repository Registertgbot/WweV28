"""WWE Arena — entry point."""
from __future__ import annotations

import asyncio
import contextlib
import logging

import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeChat, ErrorEvent

import database
from handlers.access import GroupGate
from handlers.broadcast import AlbumTracker
from handlers.broadcast import deadline_loop as broadcast_loop
from handlers.moderation import BanGate
from services import access, economy, moderation, spawns, titles
from config import get_settings, load_settings, set_settings
from handlers import routers
from services import match_engine, media_manager, mitb_engine, mitb_manager, rumble_engine, rumble_manager, tag_engine, tag_manager, tour_manager, turn_manager

log = logging.getLogger("wwe_arena")

COMMANDS = [                      # the public "/" menu (everyone sees this)
    BotCommand(command="arena", description="Open the arena menu (all game modes)"),
    BotCommand(command="start", description="Welcome screen"),
    BotCommand(command="help", description="Rules and controls"),
    BotCommand(command="match", description="Challenge someone to a 1v1 match"),
    BotCommand(command="rumble", description="Open a Royal Rumble lobby"),
    BotCommand(command="tag", description="Open a Tag Team lobby"),
    BotCommand(command="mitb", description="Open a Money in the Bank lobby"),
    BotCommand(command="tournament", description="Tournament info and registration"),
    BotCommand(command="titles", description="Current champions and belts"),
    BotCommand(command="mycard", description="Your premium player card"),
    BotCommand(command="profile", description="Your superstar profile"),
    BotCommand(command="mystats", description="Your detailed stats"),
    BotCommand(command="mycollection", description="Your collected wrestlers"),
    BotCommand(command="collect", description="Collect the wrestler that appeared"),
    BotCommand(command="fighter", description="Choose your wrestler picture"),
    BotCommand(command="daily", description="Claim your daily coins"),
    BotCommand(command="balance", description="Check your coins"),
    BotCommand(command="shop", description="Buy VIP card skins"),
    BotCommand(command="skin", description="Switch your card skin"),
    BotCommand(command="pass", description="Season Pass: levels, rewards, missions"),
    BotCommand(command="missions", description="Today's and this week's missions"),
    BotCommand(command="passboard", description="Season leaderboard"),
    BotCommand(command="leaderboard", description="Champions board"),
    BotCommand(command="rumbleboard", description="Royal Rumble leaderboard"),
    BotCommand(command="tagboard", description="Tag Team leaderboard"),
    BotCommand(command="mitbboard", description="Money in the Bank leaderboard"),
    BotCommand(command="history", description="Your recent matches"),
    BotCommand(command="briefcase", description="Your Money in the Bank briefcase"),
    BotCommand(command="cancelmatch", description="Cancel your open challenge or match"),
    BotCommand(command="cancelrumble", description="Cancel your Royal Rumble"),
    BotCommand(command="canceltag", description="Cancel your Tag Team match"),
    BotCommand(command="cancelmitb", description="Cancel your Money in the Bank"),
    BotCommand(command="id", description="Show chat and user IDs"),
    BotCommand(command="version", description="Show the running bot version"),
]
OWNER_COMMANDS = [                # shown only in the owner's own chat with the bot
    BotCommand(command="allow", description="Approve this group (or: /allow <chat_id>)"),
    BotCommand(command="disallow", description="Remove this group's approval"),
    BotCommand(command="groups", description="List approved groups"),
    BotCommand(command="approval", description="Group approval: /approval on | off | status"),
    BotCommand(command="spawn", description="Wrestler spawns: /spawn on [min] | off"),
    BotCommand(command="spawnnow", description="Spawn a wrestler right now"),
    BotCommand(command="wrestlers", description="How many wrestler cards exist"),
    BotCommand(command="delwrestler", description="Remove a wrestler card by name"),
    BotCommand(command="givecoins", description="Give coins: /givecoins 500 [user_id]"),
    BotCommand(command="givebelt", description="Give a belt: /givebelt <belt> [id]"),
    BotCommand(command="vacate", description="Vacate a belt: /vacate <belt>"),
    BotCommand(command="settings", description="Bot settings"),
    BotCommand(command="setsetting", description="Change a bot setting"),
    BotCommand(command="channeltest", description="Test the results channel"),
    BotCommand(command="broadcast", description="Reply to a message: exact copy to groups/users/all"),
    BotCommand(command="fbroadcast", description="Reply to a message: forward (shows original sender)"),
    BotCommand(command="pbroadcast", description="Personal text with {name} {coins} {cards}"),
    BotCommand(command="pollbroadcast", description="Poll / quiz broadcast"),
    BotCommand(command="broadcasts", description="Scheduled and repeating broadcasts"),
    BotCommand(command="bcancel", description="Cancel a scheduled broadcast"),
    BotCommand(command="bcstats", description="Broadcast statistics"),
    BotCommand(command="bhelp", description="Broadcast help and examples"),
    BotCommand(command="botban", description="Ban a user from the bot (reply or id)"),
    BotCommand(command="botmute", description="Mute a user: /botmute 60 (minutes)"),
    BotCommand(command="botunban", description="Lift a ban or mute"),
    BotCommand(command="banlist", description="List banned and muted users"),
    BotCommand(command="wallet", description="See a user's coins, cards and skins"),
    BotCommand(command="takecoins", description="Take coins: /takecoins 300"),
    BotCommand(command="setcoins", description="Set coins: /setcoins 1000"),
    BotCommand(command="givecard", description="Give a wrestler card: /givecard Name"),
    BotCommand(command="takecard", description="Take a wrestler card"),
    BotCommand(command="giveskin", description="Give a VIP skin: /giveskin key"),
    BotCommand(command="takeskin", description="Take a VIP skin"),
    BotCommand(command="auditlog", description="Recent owner actions"),
    BotCommand(command="seasonnew", description="Start a season: /seasonnew 30 auto Name"),
    BotCommand(command="seasonend", description="End the season and pay the top 3"),
    BotCommand(command="seasoninfo", description="Current season details"),
    BotCommand(command="givepass", description="Give the premium pass to a player"),
    BotCommand(command="addxp", description="Add or remove season XP"),
]


_last_alert = 0.0


async def on_error(event: ErrorEvent, bot: Bot) -> bool:
    global _last_alert
    log.exception("Unhandled error while processing update", exc_info=event.exception)
    update = event.update
    with contextlib.suppress(Exception):
        if update.callback_query:
            await update.callback_query.answer("⚠️ Something went wrong. Please try again.", show_alert=True)
        elif update.message:
            await update.message.answer("⚠️ Something went wrong. Please try again.")
    owner = get_settings().owner_id
    if owner and time.monotonic() - _last_alert > 60:                      # tell the owner what broke (at most once a minute)
        _last_alert = time.monotonic()
        kind = "button" if update.callback_query else (update.message.text or "message")[:40] if update.message else "update"
        with contextlib.suppress(Exception):
            await bot.send_message(owner, f"⚠️ <b>Bot error</b> on <code>{kind}</code>\n"
                                          f"<code>{type(event.exception).__name__}: {str(event.exception)[:300]}</code>",
                                   parse_mode="HTML")
    return True


async def main() -> None:
    settings = load_settings(require_token=True)
    set_settings(settings)
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)   # never log SQL parameters/secrets
    database.init_engine()
    if not await database.acquire_instance_lock():
        log.error("Another copy of this bot is already running on the same database. Stop the old one (old Railway service / other host / local run) and start again.")
        await database.dispose_engine()
        return

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.message.outer_middleware(AlbumTracker())
    dp.message.outer_middleware(BanGate())
    dp.callback_query.outer_middleware(BanGate())
    dp.message.outer_middleware(GroupGate())
    dp.callback_query.outer_middleware(GroupGate())
    for router in routers:
        dp.include_router(router)
    dp.errors.register(on_error)

    async with database.transaction() as s:
        await media_manager.ensure_assets(s)
        await access.load(s)
        await moderation.load(s)
        log.info("Roster: %s new wrestler cards imported", await spawns.import_roster(s))
        await spawns.load_active(s)
        recovered = await match_engine.recover_deadlines(s)
        recovered += await rumble_engine.recover_deadlines(s)
        recovered += await tag_engine.recover_deadlines(s)
        recovered += await mitb_engine.recover_deadlines(s)
    if recovered:
        log.info("Gave a restart grace period to %d match deadline(s)", recovered)
    missing = media_manager.missing_assets()
    if missing:
        log.warning("GIFs missing (text fallback will be used): %s", ", ".join(missing))

    me = await bot.get_me()
    await bot.set_my_commands(COMMANDS)
    if settings.owner_id:                                           # owner-only commands appear in the owner's chat only
        with contextlib.suppress(Exception):
            await bot.set_my_commands(COMMANDS + OWNER_COMMANDS, scope=BotCommandScopeChat(chat_id=settings.owner_id))
    log.info("Starting @%s", me.username)

    loop_task = asyncio.create_task(turn_manager.deadline_loop(bot), name="deadline-loop")
    rumble_task = asyncio.create_task(rumble_manager.deadline_loop(bot), name="rumble-loop")
    tag_task = asyncio.create_task(tag_manager.deadline_loop(bot), name="tag-loop")
    mitb_task = asyncio.create_task(mitb_manager.deadline_loop(bot), name="mitb-loop")
    tour_task = asyncio.create_task(tour_manager.deadline_loop(bot), name="tour-loop")
    title_task = asyncio.create_task(titles.deadline_loop(bot), name="title-loop")
    spawn_task = asyncio.create_task(spawns.deadline_loop(bot), name="spawn-loop")
    eco_task = asyncio.create_task(economy.deadline_loop(bot), name="economy-loop")
    bc_task = asyncio.create_task(broadcast_loop(bot), name="broadcast-loop")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        loop_task.cancel()
        rumble_task.cancel()
        tag_task.cancel()
        mitb_task.cancel()
        tour_task.cancel()
        title_task.cancel()
        spawn_task.cancel()
        eco_task.cancel()
        bc_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_task
        with contextlib.suppress(asyncio.CancelledError):
            await rumble_task
        with contextlib.suppress(asyncio.CancelledError):
            await tag_task
        with contextlib.suppress(asyncio.CancelledError):
            await mitb_task
        with contextlib.suppress(asyncio.CancelledError):
            await tour_task
        with contextlib.suppress(asyncio.CancelledError):
            await title_task
        with contextlib.suppress(asyncio.CancelledError):
            await spawn_task
        with contextlib.suppress(asyncio.CancelledError):
            await eco_task
        with contextlib.suppress(asyncio.CancelledError):
            await bc_task
        await bot.session.close()
        await database.dispose_engine()
        log.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
