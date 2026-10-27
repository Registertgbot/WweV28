"""My Card: a player's stats gathered from the database and drawn as a premium card."""
from __future__ import annotations

import asyncio

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import transaction
from models import Match, MatchStatus, Tournament, User
from config import get_settings
from services import cards, economy, stats, titles

TIERS = [(50, "LEGEND"), (25, "MAIN EVENTER"), (10, "CONTENDER"), (0, "ROOKIE")]       # (min wins, tier)
THEME_UNLOCK = [(5, "royal"), (3, "ice"), (1, "fire"), (0, "gold")]                      # (min titles, theme)


def tier_for(wins: int) -> str:
    return next(name for need, name in TIERS if wins >= need)


def theme_for(titles: int) -> str:
    return next(name for need, name in THEME_UNLOCK if titles >= need)


async def _best_streak(session: AsyncSession, user_id: int) -> int:
    rows = (await session.execute(
        select(Match.winner_id).where(Match.status == MatchStatus.COMPLETED,
                                      or_(Match.challenger_id == user_id, Match.opponent_id == user_id))
        .order_by(Match.id))).scalars().all()
    best = run = 0
    for winner in rows:
        run = run + 1 if winner == user_id else 0
        best = max(best, run)
    return best


async def collect(session: AsyncSession, user_id: int) -> dict:
    data = await stats.detailed_stats(session, user_id) or {"wins": 0, "losses": 0, "knockouts": 0, "finishers": 0}
    titles_won = (await session.execute(select(func.count()).select_from(Tournament).where(
        Tournament.winner_id == user_id, Tournament.status == "completed"))).scalar_one()
    user = await session.get(User, user_id)
    data.update(titles=titles_won, belts=await titles.belts_of(session, user_id), streak=await _best_streak(session, user_id),
                since=user.registered_at.strftime("Member since %b %Y") if user else "")
    return data


async def render(bot, user_id: int, name: str, username: str | None, skin: str | None = None) -> bytes:
    """Draw a player's card. Database work is short and finished before the avatar download and the image rendering,
    so no connection is held while waiting for Telegram."""
    from services import avatars
    async with transaction() as session:
        data = await collect(session, user_id)
        if skin == "default":
            theme = theme_for(data["titles"])
        else:
            theme = skin or await economy.equipped_skin(session, user_id) or theme_for(data["titles"])
    avatar = await avatars.fetch_avatar(bot, user_id)
    card = cards.ProfileCard(
        player=cards.Person(user_id, name, avatar), tier=tier_for(data["wins"]), wins=data["wins"], losses=data["losses"],
        knockouts=data["knockouts"], titles=data["titles"], finishers=data["finishers"], streak=data["streak"],
        handle=f"@{username}" if username else "", since=data["since"], theme=theme, held_belts=data["belts"],
        edition="owner" if user_id == get_settings().owner_id else "gift")
    return await asyncio.to_thread(cards.render_profile_card, card)
