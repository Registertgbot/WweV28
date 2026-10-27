"""Season Pass: XP from everything a player does, levels with a free and a premium reward track, daily / weekly missions,
a leaderboard and owner-run seasons (with top-3 prizes and automatic renewal).

XP arrives through :func:`on_event` (matches, collecting, /daily, title matches, tournaments). Nothing happens while no season runs.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models import (AllowedGroup, MissionProgress, Season, SeasonClaim, SeasonPlayer, User, UserSkin, Wrestler, WrestlerOwned, utcnow)
from services import economy
from services.cards import VIP_STYLES

log = logging.getLogger(__name__)

XP_WIN, XP_PLAY, XP_DAILY, XP_TITLE, XP_TOURNAMENT = 60, 20, 30, 150, 400
XP_COLLECT = {"common": 20, "rare": 40, "epic": 80, "legendary": 200}
TOP_PRIZES = (5000, 3000, 1500)                     # coins for the top 3 when a season ends
CLAIM_GRACE_DAYS = 7                                # rewards can still be claimed this long after a season ends
DUPLICATE_SKIN_COINS = 2000
SKIN_MILESTONES = ("retro_poster", "backstage_pass", "fight_night", "holo_trading", "black_diamond")   # premium track, at 20/40/60/80/100%


# ------------------------------------------------------------------------------------------- levels

def need(level: int) -> int:
    """XP needed to go from level-1 to level."""
    return 120 + 12 * (level - 1)


def total_xp(level: int) -> int:
    return 120 * level + 6 * level * (level - 1)


def level_for(xp: int, max_level: int) -> int:
    level = 0
    while level < max_level and xp >= total_xp(level + 1):
        level += 1
    return level


def progress(xp: int, max_level: int) -> tuple[int, int, int]:
    """(level, xp into the current level, xp the current level needs; 0 when maxed)."""
    level = level_for(xp, max_level)
    if level >= max_level:
        return level, 0, 0
    return level, xp - total_xp(level), need(level + 1)


# ------------------------------------------------------------------------------------------ rewards

def skin_levels(max_level: int) -> dict[int, str]:
    return {max(1, round(max_level * (i + 1) / 5)): key for i, key in enumerate(SKIN_MILESTONES) if key in VIP_STYLES}


def reward(level: int, track: str, max_level: int) -> tuple[str, object]:
    """('coins', n) | ('card', rarity) | ('skin', key) for a level of the free or the premium ('prem') track."""
    if track == "free":
        if level == max_level:
            return "card", "legendary"
        if level % 10 == 0:
            return "card", "rare"
        if level % 5 == 0:
            return "card", "common"
        return "coins", 40 + 4 * level
    skins = skin_levels(max_level)
    if level in skins:
        return "skin", skins[level]
    if level % 5 == 0:
        return "card", "epic" if level >= max_level // 2 else "rare"
    return "coins", 80 + 10 * level


async def _grant(session: AsyncSession, user_id: int, kind: str, value) -> str:
    if kind == "coins":
        await economy.add_coins(session, user_id, int(value))
        return f"💰 +{value} coins"
    if kind == "skin":
        if await session.get(UserSkin, (user_id, value)) is not None:
            await economy.add_coins(session, user_id, DUPLICATE_SKIN_COINS)
            return f"💰 +{DUPLICATE_SKIN_COINS} coins (you already own {economy.skin_name(value)})"
        session.add(UserSkin(user_id=user_id, skin=value))
        return f"🎨 {economy.skin_name(value)} skin"
    pool = (await session.execute(select(Wrestler).where(Wrestler.active.is_(True), Wrestler.rarity == value))).scalars().all()
    pool = pool or (await session.execute(select(Wrestler).where(Wrestler.active.is_(True)))).scalars().all()
    if not pool:
        await economy.add_coins(session, user_id, 300)
        return "💰 +300 coins (no wrestler cards yet)"
    w = random.choice(pool)
    owned = await session.get(WrestlerOwned, (user_id, w.id))
    if owned is None:
        session.add(WrestlerOwned(user_id=user_id, wrestler_id=w.id, qty=1))
    else:
        owned.qty += 1
    return f"🃏 {w.name} ({w.rarity})"


# ------------------------------------------------------------------------------------------ missions

@dataclass(frozen=True)
class Mission:
    key: str
    title: str
    target: int
    xp: int
    events: tuple[str, ...]


DAILY_POOL = (
    Mission("d_win1", "Win a match", 1, 50, ("win",)), Mission("d_win2", "Win 2 matches", 2, 90, ("win",)),
    Mission("d_play1", "Play a match", 1, 30, ("win", "play")), Mission("d_play3", "Play 3 matches", 3, 70, ("win", "play")),
    Mission("d_collect", "Collect a wrestler", 1, 80, ("collect",)), Mission("d_daily", "Claim your /daily reward", 1, 30, ("daily",)),
)
WEEKLY_POOL = (
    Mission("w_win10", "Win 10 matches", 10, 300, ("win",)), Mission("w_collect5", "Collect 5 wrestlers", 5, 250, ("collect",)),
    Mission("w_play15", "Play 15 matches", 15, 250, ("win", "play")), Mission("w_title", "Win a title match", 1, 200, ("title",)),
    Mission("w_daily5", "Claim /daily 5 times", 5, 150, ("daily",)),
)


def day_key(day: date) -> str:
    return f"d:{day.isoformat()}"


def week_key(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"w:{year}-W{week:02d}"


def daily_missions(day: date) -> list[Mission]:
    return random.Random(day.toordinal()).sample(DAILY_POOL, 3)


def weekly_missions(day: date) -> list[Mission]:
    year, week, _ = day.isocalendar()
    return random.Random(year * 100 + week).sample(WEEKLY_POOL, 3)


# ----------------------------------------------------------------------------------------- seasons

async def current(session: AsyncSession) -> Season | None:
    return (await session.execute(select(Season).where(Season.status == "active").order_by(Season.id.desc()).limit(1))).scalars().first()


async def _latest(session: AsyncSession) -> Season | None:
    return (await session.execute(select(Season).order_by(Season.id.desc()).limit(1))).scalars().first()


async def pass_season(session: AsyncSession) -> Season | None:
    """The season shown in /pass: the running one, or the last one while its claim grace period lasts."""
    season = await current(session)
    if season is not None:
        return season
    last = await _latest(session)
    return last if last and utcnow() - last.ends_at < timedelta(days=CLAIM_GRACE_DAYS) else None


async def player(session: AsyncSession, season: Season, user_id: int) -> SeasonPlayer:
    row = await session.get(SeasonPlayer, (season.id, user_id))
    if row is None:
        row = SeasonPlayer(season_id=season.id, user_id=user_id, xp=0, premium=False)
        session.add(row)
        await session.flush()
    return row


@dataclass
class Gain:
    active: bool = False
    xp: int = 0
    level: int = 0
    leveled: bool = False
    missions: list[Mission] = field(default_factory=list)

    def line(self) -> str:
        if not self.active or not self.xp:
            return ""
        text = f"⭐ +{self.xp} XP (Lv {self.level})" + (" 🎉 LEVEL UP!" if self.leveled else "")
        return text + "".join(f"\n✅ Mission: {m.title} (+{m.xp} XP)" for m in self.missions)


async def on_event(session: AsyncSession, user_id: int, event: str, xp: int = 0, amount: int = 1) -> Gain:
    """Record something a player did: add its XP, advance today's / this week's missions, report level-ups."""
    season = await current(session)
    if season is None:
        return Gain()
    sp = await player(session, season, user_id)
    before = level_for(sp.xp, season.max_level)
    total, done = xp, []
    today = economy.today_ist()
    for period, missions in ((day_key(today), daily_missions(today)), (week_key(today), weekly_missions(today))):
        for m in missions:
            if event not in m.events:
                continue
            row = await session.get(MissionProgress, (user_id, period, m.key))
            if row is None:
                row = MissionProgress(user_id=user_id, period=period, mission=m.key, progress=0, done=False)
                session.add(row)
            if row.done:
                continue
            row.progress += amount
            if row.progress >= m.target:
                row.done = True
                total += m.xp
                done.append(m)
    sp.xp += total
    after = level_for(sp.xp, season.max_level)
    return Gain(True, total, after, after > before, done)


@dataclass
class View:
    season: Season
    xp: int
    premium: bool
    level: int
    into: int
    size: int
    claimed: set[tuple[int, str]]
    waiting: list[tuple[int, str]]            # rewards earned but not collected yet
    rank: int | None


async def view(session: AsyncSession, user_id: int) -> View | None:
    season = await pass_season(session)
    if season is None:
        return None
    sp = await player(session, season, user_id)
    level, into, size = progress(sp.xp, season.max_level)
    claimed = {(r.level, r.track) for r in (await session.execute(select(SeasonClaim).where(
        SeasonClaim.season_id == season.id, SeasonClaim.user_id == user_id))).scalars().all()}
    waiting = [(lv, tr) for lv in range(1, level + 1) for tr in (("free", "prem") if sp.premium else ("free",)) if (lv, tr) not in claimed]
    better = (await session.execute(select(func.count()).select_from(SeasonPlayer).where(SeasonPlayer.season_id == season.id, SeasonPlayer.xp > sp.xp))).scalar_one()
    return View(season, sp.xp, sp.premium, level, into, size, claimed, waiting, (better + 1) if sp.xp else None)


async def claim_all(session: AsyncSession, user_id: int) -> list[str]:
    v = await view(session, user_id)
    if v is None:
        return []
    lines = []
    for level, track in v.waiting:
        kind, value = reward(level, track, v.season.max_level)
        session.add(SeasonClaim(season_id=v.season.id, user_id=user_id, level=level, track=track))
        lines.append(f"Lv {level} {'💎' if track == 'prem' else '🆓'} {await _grant(session, user_id, kind, value)}")
    return lines


async def buy_premium(session: AsyncSession, user_id: int) -> str:
    """-> ok | owned | poor | none"""
    season = await current(session)
    if season is None:
        return "none"
    sp = await player(session, season, user_id)
    if sp.premium:
        return "owned"
    if not await economy.spend(session, user_id, season.premium_price):
        return "poor"
    sp.premium = True
    return "ok"


async def leaderboard(session: AsyncSession, season: Season, limit: int = 10) -> list[tuple[int, str, int, int]]:
    rows = (await session.execute(select(SeasonPlayer).where(SeasonPlayer.season_id == season.id, SeasonPlayer.xp > 0)
                                  .order_by(SeasonPlayer.xp.desc()).limit(limit))).scalars().all()
    out = []
    for r in rows:
        user = await session.get(User, r.user_id)
        out.append((r.user_id, user.display_name if user else "Player", r.xp, level_for(r.xp, season.max_level)))
    return out


async def mission_rows(session: AsyncSession, user_id: int) -> tuple[list[tuple[Mission, int, bool]], list[tuple[Mission, int, bool]]]:
    today = economy.today_ist()
    result = []
    for period, missions in ((day_key(today), daily_missions(today)), (week_key(today), weekly_missions(today))):
        rows = []
        for m in missions:
            row = await session.get(MissionProgress, (user_id, period, m.key))
            rows.append((m, min(row.progress, m.target) if row else 0, bool(row and row.done)))
        result.append(rows)
    return result[0], result[1]


# ------------------------------------------------------------------------------------- owner / loop

async def start_season(session: AsyncSession, name: str, days: int, auto_renew: bool = False, max_level: int = 50,
                       price: int = 3000) -> Season | None:
    if await current(session) is not None:
        return None
    last = await _latest(session)
    now = utcnow()
    season = Season(number=(last.number + 1) if last else 1, name=name[:40] or "Season", starts_at=now,
                    ends_at=now + timedelta(days=max(1, days)), max_level=max_level, premium_price=price, status="active",
                    auto_renew=auto_renew)
    session.add(season)
    await session.flush()
    return season


async def end_season(session: AsyncSession, season: Season) -> str:
    """Close a season, pay the top 3 and return the announcement text."""
    season.status, season.ends_at = "ended", min(season.ends_at, utcnow())
    top = await leaderboard(session, season, 3)
    lines = [f"🏁 <b>Season {season.number} — {season.name} has ended!</b>"]
    for i, (uid, name, xp, level) in enumerate(top):
        await economy.add_coins(session, uid, TOP_PRIZES[i])
        lines.append(f"{('🥇', '🥈', '🥉')[i]} <b>{name}</b> — Lv {level}, {xp} XP • +{TOP_PRIZES[i]} coins")
    if not top:
        lines.append("Nobody played this season.")
    lines.append(f"\nUnclaimed rewards stay claimable with /pass for {CLAIM_GRACE_DAYS} more days.")
    return "\n".join(lines)


async def _group_ids(session: AsyncSession) -> list[int]:
    ids = list((await session.execute(select(AllowedGroup.chat_id))).scalars().all()) + list(get_settings().default_groups)
    return list(dict.fromkeys(ids))


async def finalize_due() -> list[tuple[int, str]]:
    """Called by the economy loop: end seasons whose time is up (and start the next one when auto-renew is on)."""
    from database import transaction
    notes: list[tuple[int, str]] = []
    async with transaction() as s:
        due = (await s.execute(select(Season).where(Season.status == "active", Season.ends_at <= utcnow()))).scalars().all()
        for season in due:
            text = await end_season(s, season)
            groups = await _group_ids(s)
            if season.auto_renew:
                days = max(1, (season.ends_at - season.starts_at).days)
                nxt = await start_season(s, f"Season {season.number + 1}", days, True, season.max_level, season.premium_price)
                if nxt is not None:
                    text += f"\n\n🚀 <b>Season {nxt.number}</b> has started! Open /pass and start climbing."
            notes += [(chat_id, text) for chat_id in groups]
    return notes
