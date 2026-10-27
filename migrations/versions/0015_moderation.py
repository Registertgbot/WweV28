"""bans, mutes and the owner audit log

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("bot_bans",
                    sa.Column("user_id", sa.BigInteger(), primary_key=True, autoincrement=False),
                    sa.Column("kind", sa.String(4), nullable=False),
                    sa.Column("until", sa.DateTime(timezone=True)),
                    sa.Column("reason", sa.String(200)),
                    sa.Column("by_id", sa.BigInteger(), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("audit_log",
                    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
                    sa.Column("at", sa.DateTime(timezone=True), nullable=False),
                    sa.Column("actor_id", sa.BigInteger(), nullable=False),
                    sa.Column("action", sa.String(24), nullable=False),
                    sa.Column("target_id", sa.BigInteger()),
                    sa.Column("detail", sa.String(300)))


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("bot_bans")
