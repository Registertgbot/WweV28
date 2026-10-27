"""One game at a time per group: a new game cannot be started while another is still open in the same chat."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Match, MatchStatus, MitbEvent, Rumble, RStatus, TagMatch

MITB_OPEN = ("lobby", "qualifier", "ladder")


async def _lock_chat(session: AsyncSession, chat_id: int) -> None:
    """Serialise game creation per group (two quick taps must not both pass the check). Postgres only; SQLite is single-writer."""
    if session.sync_session.get_bind().dialect.name == "postgresql":
        await session.execute(select(func.pg_advisory_xact_lock(chat_id)))


async def busy_game(session: AsyncSession, chat_id: int, side_games_only: bool = False) -> str | None:
    """Name of the game that is open (lobby, challenge or running) in this group, or None when it is free.

    ``side_games_only`` ignores tournament fixtures (the tournament loop uses it: fixtures of one matchday run side by side,
    but they wait while a normal game is going on)."""
    await _lock_chat(session, chat_id)
    match_q = select(Match.id).where(Match.group_chat_id == chat_id, Match.status.in_(MatchStatus.OPEN))
    if side_games_only:
        match_q = match_q.where(Match.fixture_id.is_(None))
    checks = (
        ("1v1 match", match_q),
        ("Tag Team match", select(TagMatch.id).where(TagMatch.group_chat_id == chat_id, TagMatch.status.in_(RStatus.OPEN))),
        ("Royal Rumble", select(Rumble.id).where(Rumble.group_chat_id == chat_id, Rumble.status.in_(RStatus.OPEN))),
        ("Money in the Bank", select(MitbEvent.id).where(MitbEvent.group_chat_id == chat_id, MitbEvent.status.in_(MITB_OPEN))),
    )
    for label, query in checks:
        if (await session.execute(query.limit(1))).first() is not None:
            return label
    return None


def busy_message(label: str) -> str:
    return f"⏳ A {label} is already running in this group. Wait until it finishes, then start a new game."
