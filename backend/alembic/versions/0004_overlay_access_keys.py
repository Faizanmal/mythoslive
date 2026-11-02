"""Add hashed, revocable overlay access keys."""

from alembic import op
import sqlalchemy as sa

revision = "0004_overlay_access_keys"
down_revision = "0003_engine_chronicle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "overlay_access_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("world_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["world_id"], ["worlds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_overlay_access_world_active", "overlay_access_keys", ["world_id", "revoked_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_overlay_access_world_active", table_name="overlay_access_keys")
    op.drop_table("overlay_access_keys")
