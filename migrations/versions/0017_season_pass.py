"""season pass: seasons, players, claims and mission progress

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("seasons",
                    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
                    sa.Column("number", sa.Integer(), nullable=False),
                    sa.Column("name", sa.String(40), nullable=False),
                    sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
                    sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
                    sa.Column("max_level", sa.Integer(), nullable=False, server_default="50"),
                    sa.Column("premium_price", sa.Integer(), nullable=False, server_default="3000"),
                    sa.Column("status", sa.String(8), nullable=False),
                    sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_table("season_players",
                    sa.Column("season_id", sa.Integer(), primary_key=True, autoincrement=False),
                    sa.Column("user_id", sa.BigInteger(), primary_key=True, autoincrement=False),
                    sa.Column("xp", sa.Integer(), nullable=False, server_default="0"),
                    sa.Column("premium", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_index("ix_season_players_xp", "season_players", ["season_id", "xp"])
    op.create_table("season_claims",
                    sa.Column("season_id", sa.Integer(), primary_key=True, autoincrement=False),
                    sa.Column("user_id", sa.BigInteger(), primary_key=True, autoincrement=False),
                    sa.Column("level", sa.Integer(), primary_key=True, autoincrement=False),
                    sa.Column("track", sa.String(4), primary_key=True))
    op.create_table("mission_progress",
                    sa.Column("user_id", sa.BigInteger(), primary_key=True, autoincrement=False),
                    sa.Column("period", sa.String(12), primary_key=True),
                    sa.Column("mission", sa.String(16), primary_key=True),
                    sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
                    sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_table("mission_progress")
    op.drop_table("season_claims")
    op.drop_index("ix_season_players_xp", table_name="season_players")
    op.drop_table("season_players")
    op.drop_table("seasons")
