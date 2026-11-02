"""Persist dashboard configuration and decisions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_streamer_control_room"
down_revision = "0005_consent_chronicler_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "viewers", sa.Column("muted", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.drop_constraint(op.f("ck_game_events_source"), "game_events", type_="check")
    op.create_check_constraint(
        "source", "game_events", "source IN ('twitch','simulator','dashboard')"
    )
    op.drop_constraint(
        op.f("ck_world_events_pending_status"), "world_events_pending", type_="check"
    )
    op.create_check_constraint(
        "status", "world_events_pending", "status IN ('pending','applied','rejected','expired')"
    )
    op.add_column(
        "world_events_pending", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE world_events_pending SET expires_at = created_at + interval '5 minutes' "
        "WHERE status = 'pending'"
    )
    op.create_table(
        "dashboard_configs",
        sa.Column("world_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("director_notes", sa.Text(), server_default="", nullable=False),
        sa.Column("settings", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["world_id"], ["worlds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("world_id"),
    )
    op.create_table(
        "dashboard_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("world_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_broadcaster_id", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("details", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(action) BETWEEN 1 AND 64", name="action_length"),
        sa.ForeignKeyConstraint(["world_id"], ["worlds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dashboard_audit_world_created", "dashboard_audit", ["world_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_dashboard_audit_world_created", table_name="dashboard_audit")
    op.drop_table("dashboard_audit")
    op.drop_table("dashboard_configs")
    op.drop_column("viewers", "muted")
    op.drop_column("world_events_pending", "expires_at")
    op.drop_constraint(
        op.f("ck_world_events_pending_status"), "world_events_pending", type_="check"
    )
    op.create_check_constraint(
        "status", "world_events_pending", "status IN ('pending','applied','rejected')"
    )
    op.drop_constraint(op.f("ck_game_events_source"), "game_events", type_="check")
    op.create_check_constraint("source", "game_events", "source IN ('twitch','simulator')")
