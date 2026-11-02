"""Add consent-aware, typed campaign memories."""

from alembic import op
import sqlalchemy as sa

revision = "0005_consent_chronicler_memory"
down_revision = "0004_overlay_access_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "viewers",
        sa.Column("memory_consent", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "memories",
        sa.Column("kind", sa.String(length=24), server_default="world_fact", nullable=False),
    )
    op.add_column(
        "memories",
        sa.Column("importance", sa.Float(), server_default="0.5", nullable=False),
    )
    op.add_column("memories", sa.Column("last_used_at", sa.DateTime(timezone=True)))
    op.add_column(
        "memories",
        sa.Column("use_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("memories", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.alter_column("memories", "summary", new_column_name="content")
    op.execute("UPDATE memories SET consented = false WHERE viewer_id IS NOT NULL")
    op.create_check_constraint(
        "ck_memories_kind",
        "memories",
        "kind IN ('world_fact','session_summary','viewer_moment','inside_joke','npc','location','quest')",
    )
    op.create_check_constraint(
        "ck_memories_importance_range", "memories", "importance >= 0 AND importance <= 1"
    )
    op.create_check_constraint("ck_memories_use_count_nonnegative", "memories", "use_count >= 0")
    op.create_check_constraint(
        "ck_memories_content_length", "memories", "length(content) BETWEEN 1 AND 280"
    )
    op.drop_index("ix_memories_world_viewer", table_name="memories")
    op.create_index(
        "ix_memories_world_viewer_kind", "memories", ["world_id", "viewer_id", "kind"]
    )
    op.create_index("ix_memories_world_importance", "memories", ["world_id", "importance"])


def downgrade() -> None:
    op.drop_index("ix_memories_world_importance", table_name="memories")
    op.drop_index("ix_memories_world_viewer_kind", table_name="memories")
    op.create_index("ix_memories_world_viewer", "memories", ["world_id", "viewer_id"])
    op.drop_constraint("ck_memories_content_length", "memories", type_="check")
    op.drop_constraint("ck_memories_use_count_nonnegative", "memories", type_="check")
    op.drop_constraint("ck_memories_importance_range", "memories", type_="check")
    op.drop_constraint("ck_memories_kind", "memories", type_="check")
    op.alter_column("memories", "content", new_column_name="summary")
    op.drop_column("memories", "archived_at")
    op.drop_column("memories", "use_count")
    op.drop_column("memories", "last_used_at")
    op.drop_column("memories", "importance")
    op.drop_column("memories", "kind")
    op.drop_column("viewers", "memory_consent")
