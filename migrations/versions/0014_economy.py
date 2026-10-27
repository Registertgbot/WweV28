"""coins, wallets, VIP skins

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("wallets",
                    sa.Column("user_id", sa.BigInteger(), primary_key=True, autoincrement=False),
                    sa.Column("coins", sa.Integer(), nullable=False, server_default="0"),
                    sa.Column("daily_on", sa.Date()),
                    sa.Column("daily_streak", sa.Integer(), nullable=False, server_default="0"),
                    sa.Column("skin", sa.String(24)))
    op.create_table("user_skins",
                    sa.Column("user_id", sa.BigInteger(), primary_key=True, autoincrement=False),
                    sa.Column("skin", sa.String(24), primary_key=True),
                    sa.Column("bought_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("economy_state",
                    sa.Column("key", sa.String(24), primary_key=True),
                    sa.Column("value", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("match_rewards",
                    sa.Column("kind", sa.String(1), primary_key=True),
                    sa.Column("match_id", sa.Integer(), primary_key=True, autoincrement=False))


def downgrade() -> None:
    for t in ("match_rewards", "economy_state", "user_skins", "wallets"):
        op.drop_table(t)
