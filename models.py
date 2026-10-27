"""SQLAlchemy models."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer,
                        String, UniqueConstraint, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend (SQLite returns naive values)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class MatchStatus:
    PENDING = "pending"          # open challenge in a group
    WAITING_DM = "waiting_dm"    # accepted, waiting for both players to press Start in DM
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    OPEN = (PENDING, WAITING_DM, ACTIVE, PAUSED)
    ALL = (PENDING, WAITING_DM, ACTIVE, PAUSED, COMPLETED, CANCELLED, EXPIRED)


class Phase:
    AWAIT_ATTACK = "await_attack"
    AWAIT_REVERSAL = "await_reversal"


class RStatus:
    LOBBY = "lobby"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    OPEN = (LOBBY, ACTIVE)


class RPhase:
    AWAIT_MOVE = "await_move"
    AWAIT_TARGET = "await_target"
    AWAIT_REVERSAL = "await_reversal"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)  # Telegram user ID
    username: Mapped[str | None] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(128))
    registered_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    dm_started: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    total_matches: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    wins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    losses: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    damage_dealt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    damage_received: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    knockouts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    __table_args__ = (
        CheckConstraint("wins >= 0 AND losses >= 0 AND total_matches >= 0", name="ck_users_counts_nonneg"),
        Index("ix_users_wins", "wins"),
    )


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    group_title: Mapped[str | None] = mapped_column(String(256))
    challenger_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    opponent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default=MatchStatus.PENDING)
    phase: Mapped[str | None] = mapped_column(String(16))
    active_player_id: Mapped[int | None] = mapped_column(BigInteger)
    turn_number: Mapped[int] = mapped_column(Integer, default=1)
    pending_move: Mapped[str | None] = mapped_column(String(16))
    pending_wild: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    deadline_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    winner_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    end_reason: Mapped[str | None] = mapped_column(String(24))
    cancel_requested_by: Mapped[int | None] = mapped_column(BigInteger)
    challenge_message_id: Mapped[int | None] = mapped_column(Integer)
    scoreboard_message_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    fixture_id: Mapped[int | None] = mapped_column(Integer, index=True)      # set for tournament fixtures

    players: Mapped[list["MatchPlayer"]] = relationship(
        lazy="selectin", order_by="MatchPlayer.id", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','waiting_dm','active','paused','completed','cancelled','expired')",
            name="ck_matches_status"),
        Index("ix_matches_status_deadline", "status", "deadline_at"),
    )


class MatchPlayer(Base):
    """Per-player state inside a match (HP and move usage). Survives restarts."""

    __tablename__ = "match_players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    hp: Mapped[int] = mapped_column(Integer, default=100)
    finishers_used: Mapped[int] = mapped_column(Integer, default=0)
    reversals_used: Mapped[int] = mapped_column(Integer, default=0)      # attempts, successful or not
    bonus_reversals: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    wild_draws_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_attack: Mapped[str | None] = mapped_column(String(16))
    prompt_message_id: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint("match_id", "user_id", name="uq_match_player"),
        CheckConstraint("hp >= 0 AND hp <= 100", name="ck_match_players_hp"),
        CheckConstraint("finishers_used >= 0 AND finishers_used <= 2", name="ck_match_players_finishers"),
        CheckConstraint("reversals_used >= 0 AND reversals_used <= 4", name="ck_match_players_reversals"),
        # A user may be in at most one open match at any time (DB-level guarantee).
        Index("uq_match_players_one_active_per_user", "user_id", unique=True,
              postgresql_where=text("is_active"), sqlite_where=text("is_active")),
    )


class MatchTurn(Base):
    __tablename__ = "match_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    turn_number: Mapped[int] = mapped_column(Integer)
    attacker_id: Mapped[int] = mapped_column(BigInteger)
    target_id: Mapped[int] = mapped_column(BigInteger)
    move: Mapped[str] = mapped_column(String(16))
    original_damage: Mapped[int] = mapped_column(Integer)
    reversed: Mapped[bool] = mapped_column(Boolean, default=False)      # a Reversal that SUCCEEDED
    reversal_attempted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    wild: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    damage_to_target: Mapped[int] = mapped_column(Integer, default=0)      # actually applied to the defender
    damage_to_attacker: Mapped[int] = mapped_column(Integer, default=0)    # reflected, actually applied
    attacker_hp_after: Mapped[int] = mapped_column(Integer)
    target_hp_after: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    # Hard guarantee that a turn can be resolved only once.
    __table_args__ = (UniqueConstraint("match_id", "turn_number", name="uq_match_turn_number"),)


class MediaAsset(Base):
    __tablename__ = "media_assets"

    event_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    local_path: Mapped[str] = mapped_column(String(256))
    telegram_file_id: Mapped[str | None] = mapped_column(String(256))


class BotSetting(Base):
    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(128))


# ------------------------------------------------------------------ Royal Rumble

class Rumble(Base):
    """A multiplayer Royal Rumble in one group. Separate from 1v1 matches."""

    __tablename__ = "rumbles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    group_title: Mapped[str | None] = mapped_column(String(256))
    host_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(12), default=RStatus.LOBBY)
    phase: Mapped[str | None] = mapped_column(String(16))
    active_player_id: Mapped[int | None] = mapped_column(BigInteger)
    turn_number: Mapped[int] = mapped_column(Integer, default=0)
    last_actor_order: Mapped[int] = mapped_column(Integer, default=0)
    pending_move: Mapped[str | None] = mapped_column(String(16))
    pending_target_id: Mapped[int | None] = mapped_column(BigInteger)
    deadline_at: Mapped[datetime | None] = mapped_column(UTCDateTime)      # lobby close / turn / reversal window
    next_entry_at: Mapped[datetime | None] = mapped_column(UTCDateTime)    # next wrestler walks in
    winner_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    end_reason: Mapped[str | None] = mapped_column(String(24))
    lobby_message_id: Mapped[int | None] = mapped_column(Integer)
    board_message_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    players: Mapped[list["RumblePlayer"]] = relationship(
        lazy="selectin", order_by="RumblePlayer.id", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("status IN ('lobby','active','completed','cancelled')", name="ck_rumbles_status"),
        Index("ix_rumbles_status_deadline", "status", "deadline_at"),
    )


class RumblePlayer(Base):
    __tablename__ = "rumble_players"

    # Same field names as MatchPlayer so services.rules can resolve attacks on these rows directly.
    bonus_reversals = 0

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rumble_id: Mapped[int] = mapped_column(Integer, ForeignKey("rumbles.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    entry_order: Mapped[int] = mapped_column(Integer, default=0)       # 0 until the Rumble starts
    hp: Mapped[int] = mapped_column(Integer, default=150)
    in_ring: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    eliminated: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    placement: Mapped[int | None] = mapped_column(Integer)             # 1 = winner
    eliminations: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    damage_dealt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    finishers_used: Mapped[int] = mapped_column(Integer, default=0)
    reversals_used: Mapped[int] = mapped_column(Integer, default=0)
    last_attack: Mapped[str | None] = mapped_column(String(16))
    afk_strikes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    prompt_message_id: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint("rumble_id", "user_id", name="uq_rumble_player"),
        CheckConstraint("hp >= 0 AND hp <= 150", name="ck_rumble_players_hp"),
        Index("uq_rumble_players_one_active_per_user", "user_id", unique=True,
              postgresql_where=text("is_active"), sqlite_where=text("is_active")),
    )


# ------------------------------------------------------------------ Tag Team (2v2)

class TagMatch(Base):
    """A 2v2 Tag Team match: team 1 = Lions, team 2 = Tigers."""

    __tablename__ = "tag_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    group_title: Mapped[str | None] = mapped_column(String(256))
    host_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    team_size: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    status: Mapped[str] = mapped_column(String(12), default=RStatus.LOBBY)
    phase: Mapped[str | None] = mapped_column(String(16))
    turn_number: Mapped[int] = mapped_column(Integer, default=0)
    active_team: Mapped[int | None] = mapped_column(Integer)
    active_player_id: Mapped[int | None] = mapped_column(BigInteger)
    pending_move: Mapped[str | None] = mapped_column(String(16))
    pending_target_id: Mapped[int | None] = mapped_column(BigInteger)
    t1_tag_lock: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    t2_tag_lock: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    deadline_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    winner_team: Mapped[int | None] = mapped_column(Integer)
    end_reason: Mapped[str | None] = mapped_column(String(24))
    lobby_message_id: Mapped[int | None] = mapped_column(Integer)
    board_message_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    players: Mapped[list["TagPlayer"]] = relationship(
        lazy="selectin", order_by="TagPlayer.id", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("status IN ('lobby','active','completed','cancelled')", name="ck_tag_matches_status"),
        Index("ix_tag_matches_status_deadline", "status", "deadline_at"),
    )


class TagPlayer(Base):
    __tablename__ = "tag_players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("tag_matches.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    team: Mapped[int] = mapped_column(Integer)                       # 1 = Lions, 2 = Tigers
    slot: Mapped[int] = mapped_column(Integer, default=0)            # 0 starts in the ring, 1 on the apron
    in_ring: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    eliminated: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    hp: Mapped[int] = mapped_column(Integer, default=100)
    finishers_used: Mapped[int] = mapped_column(Integer, default=0)
    reversals_used: Mapped[int] = mapped_column(Integer, default=0)
    bonus_reversals: Mapped[int] = mapped_column(Integer, default=0, server_default="0")   # handicap for the smaller team
    last_attack: Mapped[str | None] = mapped_column(String(16))
    afk_strikes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tags_made: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    eliminations: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    damage_dealt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    prompt_message_id: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint("match_id", "user_id", name="uq_tag_player"),
        CheckConstraint("team IN (1, 2)", name="ck_tag_players_team"),
        CheckConstraint("hp >= 0 AND hp <= 100", name="ck_tag_players_hp"),
        Index("uq_tag_players_one_active_per_user", "user_id", unique=True,
              postgresql_where=text("is_active"), sqlite_where=text("is_active")),
    )


# ------------------------------------------------------- Money in the Bank tournament

class MitbEvent(Base):
    """A Money in the Bank tournament: 1v1 qualifier rounds, then a ladder match for the briefcase."""

    __tablename__ = "mitb_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    group_title: Mapped[str | None] = mapped_column(String(256))
    host_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    mode: Mapped[str] = mapped_column(String(6), default="fast")           # fast | slow
    capacity: Mapped[int] = mapped_column(Integer, default=8)
    status: Mapped[str] = mapped_column(String(12), default="lobby")       # lobby|qualifier|ladder|completed|cancelled
    round_no: Mapped[int] = mapped_column(Integer, default=0)
    phase: Mapped[str | None] = mapped_column(String(16))                  # ladder phase
    turn_number: Mapped[int] = mapped_column(Integer, default=0)
    ladder_turns: Mapped[int] = mapped_column(Integer, default=0)
    active_player_id: Mapped[int | None] = mapped_column(BigInteger)
    pending_move: Mapped[str | None] = mapped_column(String(16))
    pending_target_id: Mapped[int | None] = mapped_column(BigInteger)
    deadline_at: Mapped[datetime | None] = mapped_column(UTCDateTime)      # lobby close / ladder turn
    winner_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    end_reason: Mapped[str | None] = mapped_column(String(24))
    lobby_message_id: Mapped[int | None] = mapped_column(Integer)
    board_message_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    players: Mapped[list["MitbPlayer"]] = relationship(
        lazy="selectin", order_by="MitbPlayer.id", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("status IN ('lobby','qualifier','ladder','completed','cancelled')", name="ck_mitb_events_status"),
        Index("ix_mitb_events_status_deadline", "status", "deadline_at"),
    )


class MitbPlayer(Base):
    __tablename__ = "mitb_players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("mitb_events.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10), default="alive")       # alive|out|ladder|dq|champion
    had_bye: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    out_round: Mapped[int | None] = mapped_column(Integer)
    # ladder-match state (same field names as MatchPlayer so services.rules works on these rows)
    rung: Mapped[int] = mapped_column(Integer, default=0)
    hp: Mapped[int] = mapped_column(Integer, default=100)
    finishers_used: Mapped[int] = mapped_column(Integer, default=0)
    reversals_used: Mapped[int] = mapped_column(Integer, default=0)
    bonus_reversals: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_attack: Mapped[str | None] = mapped_column(String(16))
    afk_strikes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    stun: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    damage_dealt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ladder_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    prompt_message_id: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint("event_id", "user_id", name="uq_mitb_player"),
        CheckConstraint("hp >= 0 AND hp <= 100", name="ck_mitb_players_hp"),
        CheckConstraint("rung >= 0 AND rung <= 5", name="ck_mitb_players_rung"),
        Index("uq_mitb_players_one_active_per_user", "user_id", unique=True,
              postgresql_where=text("is_active"), sqlite_where=text("is_active")),
    )


class Briefcase(Base):
    """The Money in the Bank briefcase: one active per holder, valid for 7 days, cash-in once."""

    __tablename__ = "briefcases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    group_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    event_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(8), default="active")       # active|won|lost|expired
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (
        Index("uq_briefcases_one_active_per_user", "user_id", unique=True,
              postgresql_where=text("status = 'active'"), sqlite_where=text("status = 'active'")),
    )


class MitbDuel(Base):
    """A 1v1 duel: a qualifier match, or a briefcase cash-in match."""

    __tablename__ = "mitb_duels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("mitb_events.id", ondelete="CASCADE"), index=True)
    group_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(8), default="bracket")        # bracket | cashin
    mode: Mapped[str] = mapped_column(String(6), default="fast")
    round_no: Mapped[int] = mapped_column(Integer, default=0)
    briefcase_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("briefcases.id"))
    status: Mapped[str] = mapped_column(String(10), default="active")      # active | completed
    phase: Mapped[str | None] = mapped_column(String(16))
    turn_number: Mapped[int] = mapped_column(Integer, default=0)
    active_user_id: Mapped[int | None] = mapped_column(BigInteger)
    pending_move: Mapped[str | None] = mapped_column(String(16))
    deadline_at: Mapped[datetime | None] = mapped_column(UTCDateTime)      # current turn / reversal window
    cap_at: Mapped[datetime | None] = mapped_column(UTCDateTime)           # hard time limit for the whole duel
    winner_id: Mapped[int | None] = mapped_column(BigInteger)
    end_reason: Mapped[str | None] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    players: Mapped[list["MitbDuelPlayer"]] = relationship(
        lazy="selectin", order_by="MitbDuelPlayer.id", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_mitb_duels_status_deadline", "status", "deadline_at"),)


class MitbDuelPlayer(Base):
    __tablename__ = "mitb_duel_players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    duel_id: Mapped[int] = mapped_column(Integer, ForeignKey("mitb_duels.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    hp: Mapped[int] = mapped_column(Integer, default=100)
    finishers_used: Mapped[int] = mapped_column(Integer, default=0)
    reversals_used: Mapped[int] = mapped_column(Integer, default=0)
    bonus_reversals: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_attack: Mapped[str | None] = mapped_column(String(16))
    afk_strikes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    damage_dealt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    prompt_message_id: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint("duel_id", "user_id", name="uq_mitb_duel_player"),
        CheckConstraint("hp >= 0 AND hp <= 100", name="ck_mitb_duel_players_hp"),
        Index("uq_mitb_duel_players_one_active_per_user", "user_id", unique=True,
              postgresql_where=text("is_active"), sqlite_where=text("is_active")),
    )


class CashinOffer(Base):
    """A 20-second window after a 1v1 match in which the briefcase holder may cash in on the winner."""

    __tablename__ = "cashin_offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    briefcase_id: Mapped[int] = mapped_column(Integer, ForeignKey("briefcases.id"), index=True)
    group_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    target_user_id: Mapped[int] = mapped_column(BigInteger)
    target_hp: Mapped[int] = mapped_column(Integer, default=100)
    status: Mapped[str] = mapped_column(String(8), default="open")         # open|taken|expired
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    message_id: Mapped[int | None] = mapped_column(Integer)


class Tournament(Base):
    """A solo knockout tournament in one group, run by the bot owner (fixtures are timed in IST by the owner)."""

    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    group_title: Mapped[str | None] = mapped_column(String(256))
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), default="registration")
    format: Mapped[str] = mapped_column(String(10), default="league", server_default="knockout")   # league|knockout
    league_rounds: Mapped[int] = mapped_column(Integer, default=0, server_default="0")             # matchdays before playoffs
    max_players: Mapped[int] = mapped_column(Integer, default=16)
    bracket_size: Mapped[int | None] = mapped_column(Integer)
    total_rounds: Mapped[int | None] = mapped_column(Integer)
    reg_close_at: Mapped[datetime | None] = mapped_column(UTCDateTime)         # auto-start time
    start_at: Mapped[datetime | None] = mapped_column(UTCDateTime)             # first round start (IST chosen by owner)
    round_gap_min: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    match_gap_min: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    noshow_sec: Mapped[int] = mapped_column(Integer, default=300, server_default="300")
    paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    winner_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    registration_message_id: Mapped[int | None] = mapped_column(Integer)
    bracket_message_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    players: Mapped[list["TournamentPlayer"]] = relationship(
        lazy="selectin", order_by="TournamentPlayer.id", cascade="all, delete-orphan")
    fixtures: Mapped[list["TournamentFixture"]] = relationship(
        lazy="selectin", order_by="TournamentFixture.id", cascade="all, delete-orphan")
    reschedules: Mapped[list["TournamentReschedule"]] = relationship(
        lazy="selectin", order_by="TournamentReschedule.id", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("status IN ('registration','active','completed','cancelled')", name="ck_tournaments_status"),
        # one open tournament per group
        Index("uq_tournaments_one_open_per_chat", "group_chat_id", unique=True,
              postgresql_where=text("status IN ('registration','active')"),
              sqlite_where=text("status IN ('registration','active')")),
    )


class TournamentPlayer(Base):
    __tablename__ = "tournament_players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tournament_id: Mapped[int] = mapped_column(Integer, ForeignKey("tournaments.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="registered")   # registered|waitlist|eliminated|champion|dq
    seed: Mapped[int | None] = mapped_column(Integer)
    out_round: Mapped[int | None] = mapped_column(Integer)
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    wins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    losses: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint("tournament_id", "user_id", name="uq_tournament_player"),
        # fair play: a user can sit in at most one open tournament at a time (DB-level guarantee)
        Index("uq_tournament_players_one_active_per_user", "user_id", unique=True,
              postgresql_where=text("is_active"), sqlite_where=text("is_active")),
    )


class TournamentFixture(Base):
    __tablename__ = "tournament_fixtures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tournament_id: Mapped[int] = mapped_column(Integer, ForeignKey("tournaments.id", ondelete="CASCADE"), index=True)
    round_no: Mapped[int] = mapped_column(Integer)
    slot: Mapped[int] = mapped_column(Integer)
    p1_id: Mapped[int | None] = mapped_column(BigInteger)
    p2_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(10), default="pending")     # pending|scheduled|live|done
    winner_id: Mapped[int | None] = mapped_column(BigInteger)
    result: Mapped[str | None] = mapped_column(String(12))                  # knockout|timeout|walkover|bye|owner
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    time_locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    reminded: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    blocked_since: Mapped[datetime | None] = mapped_column(UTCDateTime)
    match_id: Mapped[int | None] = mapped_column(Integer)
    margin: Mapped[int | None] = mapped_column(Integer)                     # winner HP - loser HP (league tiebreak)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    __table_args__ = (
        UniqueConstraint("tournament_id", "round_no", "slot", name="uq_tournament_fixture_slot"),
        CheckConstraint("status IN ('pending','scheduled','live','done')", name="ck_tournament_fixtures_status"),
        Index("ix_tournament_fixtures_status_time", "status", "scheduled_at"),
    )


class TournamentReschedule(Base):
    """A player's request to move a scheduled tournament match; the opponent (or the owner) accepts or declines."""

    __tablename__ = "tournament_reschedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tournament_id: Mapped[int] = mapped_column(Integer, ForeignKey("tournaments.id", ondelete="CASCADE"), index=True)
    fixture_id: Mapped[int] = mapped_column(Integer, index=True)
    requester_id: Mapped[int] = mapped_column(BigInteger)
    opponent_id: Mapped[int] = mapped_column(BigInteger)
    old_at: Mapped[datetime] = mapped_column(UTCDateTime)                    # time of the fixture when it was requested
    new_at: Mapped[datetime] = mapped_column(UTCDateTime)                    # proposed time
    status: Mapped[str] = mapped_column(String(10), default="pending")      # pending|accepted|declined|expired|withdrawn
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    decided_by: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        CheckConstraint("status IN ('pending','accepted','declined','expired','withdrawn')",
                        name="ck_tournament_reschedules_status"),
        # at most one open request per fixture (database-enforced)
        Index("uq_tournament_reschedules_one_pending", "fixture_id", unique=True,
              postgresql_where=text("status = 'pending'"), sqlite_where=text("status = 'pending'")),
    )


class AllowedGroup(Base):
    """Groups the owner approved with /allow (DEFAULT_GROUP_ID groups are always allowed)."""

    __tablename__ = "allowed_groups"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    title: Mapped[str | None] = mapped_column(String(256))
    approved_by: Mapped[int] = mapped_column(BigInteger)
    approved_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class UserFighter(Base):
    """The wrestler picture a player chose for his cards (file stem in assets/wrestlers)."""

    __tablename__ = "user_fighters"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    fighter: Mapped[str] = mapped_column(String(64))


class Championship(Base):
    """One of the belts; holder2 is only used by the tag-team belt."""

    __tablename__ = "championships"

    key: Mapped[str] = mapped_column(String(16), primary_key=True)
    holder1_id: Mapped[int | None] = mapped_column(BigInteger)
    holder2_id: Mapped[int | None] = mapped_column(BigInteger)
    since: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reigns: Mapped[int] = mapped_column(Integer, default=0, server_default="0")        # how many reigns this belt has had
    defenses: Mapped[int] = mapped_column(Integer, default=0, server_default="0")      # of the current reign


class TitleMatch(Base):
    """A match fought for a belt; the winner (or winning team) takes it when the match completes."""

    __tablename__ = "title_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    belt: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(6))                                       # solo | tag
    match_id: Mapped[int] = mapped_column(Integer)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (Index("ix_title_matches_open", "resolved", "belt"),)


class Wrestler(Base):
    """A collectible wrestler card (the picture is a Telegram file_id the owner sent to the bot)."""

    __tablename__ = "wrestlers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    name_norm: Mapped[str] = mapped_column(String(64), index=True)
    rarity: Mapped[str] = mapped_column(String(10), default="common")
    brand: Mapped[str | None] = mapped_column(String(32))
    file_id: Mapped[str] = mapped_column(String(256))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SpawnGroup(Base):
    """Groups where a wrestler appears every ``interval_min`` minutes (owner: /spawn on)."""

    __tablename__ = "spawn_groups"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    interval_min: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    next_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class WrestlerSpawn(Base):
    __tablename__ = "wrestler_spawns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    wrestler_id: Mapped[int] = mapped_column(Integer)
    message_id: Mapped[int | None] = mapped_column(Integer)
    spawned_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    claimed_by: Mapped[int | None] = mapped_column(BigInteger)
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    expired: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class WrestlerOwned(Base):
    __tablename__ = "wrestler_owned"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    wrestler_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    qty: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    first_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Wallet(Base):
    """A player's coins, daily-claim streak and the VIP card skin he has equipped."""

    __tablename__ = "wallets"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    coins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    daily_on: Mapped[date | None] = mapped_column(Date)
    daily_streak: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    skin: Mapped[str | None] = mapped_column(String(24))


class UserSkin(Base):
    __tablename__ = "user_skins"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    skin: Mapped[str] = mapped_column(String(24), primary_key=True)
    bought_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class EconomyState(Base):
    __tablename__ = "economy_state"

    key: Mapped[str] = mapped_column(String(24), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


class MatchReward(Base):
    """Matches whose coins were already paid out (kind: m = 1v1 / tournament, t = tag)."""

    __tablename__ = "match_rewards"

    kind: Mapped[str] = mapped_column(String(1), primary_key=True)
    match_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)


class BotBan(Base):
    """A user the owner banned (until is NULL) or muted (until = when it ends) from the bot."""

    __tablename__ = "bot_bans"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    kind: Mapped[str] = mapped_column(String(4))                                 # ban | mute
    until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reason: Mapped[str | None] = mapped_column(String(200))
    by_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuditLog(Base):
    """Owner actions that change somebody's coins, cards, skins, belts or access."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    actor_id: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    detail: Mapped[str | None] = mapped_column(String(300))


class BroadcastJob(Base):
    """A broadcast the owner confirmed: sent at once, scheduled (run_at) and/or repeating (daily / weekly)."""

    __tablename__ = "broadcast_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger)
    mode: Mapped[str] = mapped_column(String(8))                       # copy | forward | text | poll
    kind: Mapped[str] = mapped_column(String(120), default="all")      # audience: groups|users|all|vip|champions|collectors|players|chat:<id>|ids:a,b
    pin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    silent: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    personalize: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    reward: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    text: Mapped[str | None] = mapped_column(String(4000))             # message text, or the poll as JSON
    buttons: Mapped[str | None] = mapped_column(String(1500))          # JSON rows of [label, url]
    src_chat: Mapped[int | None] = mapped_column(BigInteger)
    src_ids: Mapped[str | None] = mapped_column(String(600))           # comma separated message ids (an album has several)
    run_at: Mapped[datetime] = mapped_column(UTCDateTime)
    repeat: Mapped[str | None] = mapped_column(String(8))              # daily | weekly
    status: Mapped[str] = mapped_column(String(10), default="pending") # pending | running | done | cancelled
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class BroadcastRun(Base):
    """One delivery run of a broadcast (the data behind /bcstats)."""

    __tablename__ = "broadcast_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int | None] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    mode: Mapped[str] = mapped_column(String(8))
    kind: Mapped[str] = mapped_column(String(120))
    total: Mapped[int] = mapped_column(Integer, default=0)
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    reward_total: Mapped[int] = mapped_column(Integer, default=0)
    problems: Mapped[str | None] = mapped_column(String(300))


class RewardDrop(Base):
    """A reward broadcast posted in groups: every member can claim ``coins`` once until it expires."""

    __tablename__ = "reward_drops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    coins: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class RewardClaim(Base):
    __tablename__ = "reward_claims"

    drop_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)


class Season(Base):
    """A season-pass season (the owner starts and ends them)."""

    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(40))
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime)
    max_level: Mapped[int] = mapped_column(Integer, default=50, server_default="50")
    premium_price: Mapped[int] = mapped_column(Integer, default=3000, server_default="3000")
    status: Mapped[str] = mapped_column(String(8), default="active")            # active | ended
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class SeasonPlayer(Base):
    __tablename__ = "season_players"

    season_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    xp: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    premium: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class SeasonClaim(Base):
    """A pass reward the player has already collected (track: free | prem)."""

    __tablename__ = "season_claims"

    season_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    level: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    track: Mapped[str] = mapped_column(String(4), primary_key=True)


class MissionProgress(Base):
    """Progress on one daily ('d:YYYY-MM-DD') or weekly ('w:YYYY-Www') mission."""

    __tablename__ = "mission_progress"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    period: Mapped[str] = mapped_column(String(12), primary_key=True)
    mission: Mapped[str] = mapped_column(String(16), primary_key=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    done: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
