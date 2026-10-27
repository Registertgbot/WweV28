"""broadcast jobs, runs (statistics) and reward drops

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("broadcast_jobs",
                    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
                    sa.Column("owner_id", sa.BigInteger(), nullable=False),
                    sa.Column("mode", sa.String(8), nullable=False),
                    sa.Column("kind", sa.String(120), nullable=False),
                    sa.Column("pin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
                    sa.Column("silent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
                    sa.Column("personalize", sa.Boolean(), nullable=False, server_default=sa.text("false")),
                    sa.Column("reward", sa.Integer(), nullable=False, server_default="0"),
                    sa.Column("text", sa.String(4000)),
                    sa.Column("buttons", sa.String(1500)),
                    sa.Column("src_chat", sa.BigInteger()),
                    sa.Column("src_ids", sa.String(600)),
                    sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
                    sa.Column("repeat", sa.String(8)),
                    sa.Column("status", sa.String(10), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("broadcast_runs",
                    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
                    sa.Column("job_id", sa.Integer()),
                    sa.Column("at", sa.DateTime(timezone=True), nullable=False),
                    sa.Column("mode", sa.String(8), nullable=False),
                    sa.Column("kind", sa.String(120), nullable=False),
                    sa.Column("total", sa.Integer(), nullable=False),
                    sa.Column("sent", sa.Integer(), nullable=False),
                    sa.Column("failed", sa.Integer(), nullable=False),
                    sa.Column("reward_total", sa.Integer(), nullable=False),
                    sa.Column("problems", sa.String(300)))
    op.create_table("reward_drops",
                    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
                    sa.Column("coins", sa.Integer(), nullable=False),
                    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("reward_claims",
                    sa.Column("drop_id", sa.Integer(), primary_key=True, autoincrement=False),
                    sa.Column("user_id", sa.BigInteger(), primary_key=True, autoincrement=False))


def downgrade() -> None:
    for t in ("reward_claims", "reward_drops", "broadcast_runs", "broadcast_jobs"):
        op.drop_table(t)
