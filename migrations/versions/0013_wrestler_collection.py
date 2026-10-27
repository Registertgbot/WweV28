"""collectible wrestlers: cards, spawn groups, spawns, collections

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wrestlers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("name_norm", sa.String(64), nullable=False),
        sa.Column("rarity", sa.String(10), nullable=False),
        sa.Column("brand", sa.String(32)),
        sa.Column("file_id", sa.String(256), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_wrestlers_name_norm", "wrestlers", ["name_norm"])
    op.create_table(
        "spawn_groups",
        sa.Column("chat_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("interval_min", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("next_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "wrestler_spawns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("wrestler_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer()),
        sa.Column("spawned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by", sa.BigInteger()),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("expired", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_wrestler_spawns_chat_id", "wrestler_spawns", ["chat_id"])
    op.create_table(
        "wrestler_owned",
        sa.Column("user_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("wrestler_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("qty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("wrestler_owned")
    op.drop_index("ix_wrestler_spawns_chat_id", table_name="wrestler_spawns")
    op.drop_table("wrestler_spawns")
    op.drop_table("spawn_groups")
    op.drop_index("ix_wrestlers_name_norm", table_name="wrestlers")
    op.drop_table("wrestlers")
