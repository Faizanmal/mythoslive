"""Store Twitch identity alongside each OAuth role."""

from alembic import op
import sqlalchemy as sa

revision = "0002_oauth_twitch_user_id"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("oauth_tokens", sa.Column("twitch_user_id", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("oauth_tokens", "twitch_user_id")
