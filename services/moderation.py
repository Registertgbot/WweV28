"""Bans and mutes (cached, so every update can be checked without a database hit) and the owner audit log."""
from __future__ import annotations

import time
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AuditLog, BotBan, utcnow

_bans: dict[int, tuple[str, object, str | None]] = {}          # user_id -> (kind, until | None, reason)
_noticed: dict[int, float] = {}
NOTICE_COOLDOWN = 300


async def load(session: AsyncSession) -> None:
    _bans.clear()
    for row in (await session.execute(select(BotBan))).scalars().all():
        _bans[row.user_id] = (row.kind, row.until, row.reason)


def status(user_id: int) -> tuple[str, object, str | None] | None:
    """(kind, until, reason) while the user is banned or muted, else None. Finished mutes disappear on their own."""
    hit = _bans.get(user_id)
    if hit is None:
        return None
    if hit[0] == "mute" and hit[1] is not None and hit[1] <= utcnow():
        _bans.pop(user_id, None)
        return None
    return hit


def should_notice(user_id: int) -> bool:
    now = time.monotonic()
    if now - _noticed.get(user_id, -1e9) < NOTICE_COOLDOWN:
        return False
    _noticed[user_id] = now
    return True


async def punish(session: AsyncSession, user_id: int, kind: str, minutes: int | None, reason: str | None, by_id: int) -> None:
    until = utcnow() + timedelta(minutes=minutes) if kind == "mute" and minutes else None
    row = await session.get(BotBan, user_id)
    if row is None:
        row = BotBan(user_id=user_id, kind=kind, by_id=by_id)
        session.add(row)
    row.kind, row.until, row.reason, row.by_id, row.created_at = kind, until, (reason or None) and reason[:200], by_id, utcnow()
    _bans[user_id] = (kind, until, row.reason)


async def lift(session: AsyncSession, user_id: int) -> bool:
    res = await session.execute(delete(BotBan).where(BotBan.user_id == user_id))
    _bans.pop(user_id, None)
    return bool(res.rowcount)


async def listing(session: AsyncSession) -> list[BotBan]:
    return list((await session.execute(select(BotBan).order_by(BotBan.created_at.desc()).limit(40))).scalars().all())


async def audit(session: AsyncSession, actor_id: int, action: str, target_id: int | None = None, detail: str = "") -> None:
    session.add(AuditLog(actor_id=actor_id, action=action[:24], target_id=target_id, detail=detail[:300] or None))


async def recent_audit(session: AsyncSession, limit: int = 15) -> list[AuditLog]:
    return list((await session.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))).scalars().all())
