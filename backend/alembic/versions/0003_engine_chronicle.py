"""Add durable engine identities and chronicles."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_engine_chronicle"
down_revision = "0002_oauth_twitch_user_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_viewer_world_twitch_user", "viewers", type_="unique")
    op.alter_column("viewers", "twitch_user_id", existing_type=sa.String(32), nullable=True)
    op.add_column("viewers", sa.Column("identity_key", sa.String(96), nullable=True))
    op.add_column(
        "viewers",
        sa.Column("identity_kind", sa.String(16), server_default="twitch", nullable=False),
    )
    op.execute("UPDATE viewers SET identity_key = 'twitch:' || twitch_user_id")
    op.alter_column("viewers", "identity_key", nullable=False)
    op.create_unique_constraint(
        "uq_viewer_world_identity", "viewers", ["world_id", "identity_key"]
    )
    op.add_column("viewers", sa.Column("optout_key", sa.String(64), nullable=True))
    op.create_unique_constraint(
        "uq_viewer_world_optout_key", "viewers", ["world_id", "optout_key"]
    )
    op.create_check_constraint(
        "ck_viewers_identity_kind", "viewers", "identity_kind IN ('twitch','simulator')"
    )
    op.create_table(
        "chronicles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("world_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("recap", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["world_id"], ["worlds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_chronicle_session"),
    )
    op.create_index("ix_chronicles_world_created", "chronicles", ["world_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_chronicles_world_created", table_name="chronicles")
    op.drop_table("chronicles")
    op.drop_constraint("ck_viewers_identity_kind", "viewers", type_="check")
    op.drop_constraint("uq_viewer_world_optout_key", "viewers", type_="unique")
    op.drop_column("viewers", "optout_key")
    op.drop_constraint("uq_viewer_world_identity", "viewers", type_="unique")
    op.drop_column("viewers", "identity_kind")
    op.drop_column("viewers", "identity_key")
    op.alter_column("viewers", "twitch_user_id", existing_type=sa.String(32), nullable=False)
    op.create_unique_constraint(
        "uq_viewer_world_twitch_user", "viewers", ["world_id", "twitch_user_id"]
    )
