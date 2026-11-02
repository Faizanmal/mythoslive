"""Initial MythosLive relational schema."""
import os

from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    dimension = os.getenv("EMBEDDING_DIMENSION", "").strip()
    if dimension and (not dimension.isdecimal() or int(dimension) < 1):
        raise ValueError("EMBEDDING_DIMENSION must be a positive integer or omitted")
    vector_type = f"VECTOR({int(dimension)})" if dimension else "VECTOR"

    op.execute("""CREATE TABLE channels (
	id UUID NOT NULL, 
	twitch_broadcaster_id VARCHAR(32) NOT NULL, 
	display_name VARCHAR(128) NOT NULL, 
	status VARCHAR(24) DEFAULT 'active' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_channels PRIMARY KEY (id), 
	CONSTRAINT uq_channels_twitch_broadcaster_id UNIQUE (twitch_broadcaster_id)
)""")

    op.execute("""CREATE TABLE oauth_tokens (
	id UUID NOT NULL, 
	channel_id UUID NOT NULL, 
	role VARCHAR(16) NOT NULL, 
	access_token_encrypted BYTEA NOT NULL, 
	refresh_token_encrypted BYTEA, 
	scopes VARCHAR(128)[] DEFAULT '{}' NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_oauth_tokens PRIMARY KEY (id), 
	CONSTRAINT uq_oauth_channel_role UNIQUE (channel_id, role), 
	CONSTRAINT ck_oauth_tokens_role CHECK (role IN ('broadcaster','bot')), 
	CONSTRAINT fk_oauth_tokens_channel_id_channels FOREIGN KEY(channel_id) REFERENCES channels (id) ON DELETE CASCADE
)""")

    op.execute("""CREATE TABLE worlds (
	id UUID NOT NULL, 
	channel_id UUID NOT NULL, 
	slug VARCHAR(64) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	state JSONB DEFAULT '{}' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_worlds PRIMARY KEY (id), 
	CONSTRAINT uq_world_channel_slug UNIQUE (channel_id, slug), 
	CONSTRAINT fk_worlds_channel_id_channels FOREIGN KEY(channel_id) REFERENCES channels (id) ON DELETE CASCADE
)""")

    op.execute("""CREATE TABLE sessions (
	id UUID NOT NULL, 
	world_id UUID NOT NULL, 
	state VARCHAR(16) DEFAULT 'LOBBY' NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE, 
	ended_at TIMESTAMP WITH TIME ZONE, 
	snapshot JSONB DEFAULT '{}' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_sessions PRIMARY KEY (id), 
	CONSTRAINT ck_sessions_state CHECK (state IN ('LOBBY','INTRO','VOTE','COMBAT','PUZZLE','EVENT','BOSS','RECAP','ENDED','PAUSED')), 
	CONSTRAINT fk_sessions_world_id_worlds FOREIGN KEY(world_id) REFERENCES worlds (id) ON DELETE CASCADE
)""")

    op.execute("""CREATE TABLE viewers (
	id UUID NOT NULL, 
	world_id UUID NOT NULL, 
	twitch_user_id VARCHAR(32) NOT NULL, 
	display_name VARCHAR(128), 
	opted_out BOOLEAN DEFAULT 'false' NOT NULL, 
	opted_out_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_viewers PRIMARY KEY (id), 
	CONSTRAINT uq_viewer_world_twitch_user UNIQUE (world_id, twitch_user_id), 
	CONSTRAINT fk_viewers_world_id_worlds FOREIGN KEY(world_id) REFERENCES worlds (id) ON DELETE CASCADE
)""")

    op.execute("""CREATE TABLE game_events (
	id UUID NOT NULL, 
	event_id UUID NOT NULL, 
	world_id UUID NOT NULL, 
	session_id UUID, 
	actor_viewer_id UUID, 
	event_type VARCHAR(96) NOT NULL, 
	source VARCHAR(16) NOT NULL, 
	schema_version INTEGER NOT NULL, 
	payload JSONB NOT NULL, 
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_game_events PRIMARY KEY (id), 
	CONSTRAINT uq_game_event_id UNIQUE (event_id), 
	CONSTRAINT ck_game_events_source CHECK (source IN ('twitch','simulator')), 
	CONSTRAINT ck_game_events_schema_version CHECK (schema_version >= 1), 
	CONSTRAINT fk_game_events_world_id_worlds FOREIGN KEY(world_id) REFERENCES worlds (id) ON DELETE CASCADE, 
	CONSTRAINT fk_game_events_session_id_sessions FOREIGN KEY(session_id) REFERENCES sessions (id) ON DELETE SET NULL, 
	CONSTRAINT fk_game_events_actor_viewer_id_viewers FOREIGN KEY(actor_viewer_id) REFERENCES viewers (id) ON DELETE SET NULL
)""")
    op.execute("""CREATE INDEX ix_game_events_world_occurred ON game_events (world_id, occurred_at)""")
    op.execute("""CREATE INDEX ix_game_events_session_occurred ON game_events (session_id, occurred_at)""")

    op.execute("""CREATE TABLE heroes (
	id UUID NOT NULL, 
	world_id UUID NOT NULL, 
	viewer_id UUID NOT NULL, 
	class_name VARCHAR(16), 
	stats JSONB DEFAULT '{}' NOT NULL, 
	xp BIGINT DEFAULT '0' NOT NULL, 
	cosmetic_gold BIGINT DEFAULT '0' NOT NULL, 
	cosmetics VARCHAR(64)[] DEFAULT '{}' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_heroes PRIMARY KEY (id), 
	CONSTRAINT uq_hero_world_viewer UNIQUE (world_id, viewer_id), 
	CONSTRAINT ck_heroes_class_name CHECK (class_name IS NULL OR class_name IN ('warrior','mage','rogue','cleric','bard')), 
	CONSTRAINT ck_heroes_nonnegative_rewards CHECK (xp >= 0 AND cosmetic_gold >= 0), 
	CONSTRAINT fk_heroes_world_id_worlds FOREIGN KEY(world_id) REFERENCES worlds (id) ON DELETE CASCADE, 
	CONSTRAINT fk_heroes_viewer_id_viewers FOREIGN KEY(viewer_id) REFERENCES viewers (id) ON DELETE CASCADE
)""")

    op.execute("""CREATE TABLE llm_calls (
	id UUID NOT NULL, 
	world_id UUID, 
	session_id UUID, 
	model_name VARCHAR(128) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	latency_ms INTEGER, 
	input_tokens INTEGER, 
	output_tokens INTEGER, 
	metadata_json JSONB DEFAULT '{}' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_llm_calls PRIMARY KEY (id), 
	CONSTRAINT ck_llm_calls_status CHECK (status IN ('success','error','rejected','fallback')), 
	CONSTRAINT ck_llm_calls_latency_nonnegative CHECK (latency_ms IS NULL OR latency_ms >= 0), 
	CONSTRAINT ck_llm_calls_input_tokens_nonnegative CHECK (input_tokens IS NULL OR input_tokens >= 0), 
	CONSTRAINT ck_llm_calls_output_tokens_nonnegative CHECK (output_tokens IS NULL OR output_tokens >= 0), 
	CONSTRAINT fk_llm_calls_world_id_worlds FOREIGN KEY(world_id) REFERENCES worlds (id) ON DELETE SET NULL, 
	CONSTRAINT fk_llm_calls_session_id_sessions FOREIGN KEY(session_id) REFERENCES sessions (id) ON DELETE SET NULL
)""")
    op.execute("""CREATE INDEX ix_llm_calls_world_created ON llm_calls (world_id, created_at)""")

    memory_ddl = """CREATE TABLE memories (
	id UUID NOT NULL, 
	world_id UUID NOT NULL, 
	viewer_id UUID, 
	summary TEXT NOT NULL, 
	embedding {vector_type}, 
	embedding_model VARCHAR(128), 
	consented BOOLEAN DEFAULT 'false' NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_memories PRIMARY KEY (id), 
	CONSTRAINT fk_memories_world_id_worlds FOREIGN KEY(world_id) REFERENCES worlds (id) ON DELETE CASCADE, 
	CONSTRAINT fk_memories_viewer_id_viewers FOREIGN KEY(viewer_id) REFERENCES viewers (id) ON DELETE CASCADE
)""".replace("embedding {vector_type},", f"embedding {vector_type},")
    op.execute(memory_ddl)
    op.execute("""CREATE INDEX ix_memories_world_viewer ON memories (world_id, viewer_id)""")

    op.execute("""CREATE TABLE scenes (
	id UUID NOT NULL, 
	session_id UUID NOT NULL, 
	sequence INTEGER NOT NULL, 
	kind VARCHAR(24) NOT NULL, 
	content TEXT DEFAULT '' NOT NULL, 
	state JSONB DEFAULT '{}' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_scenes PRIMARY KEY (id), 
	CONSTRAINT uq_scene_session_sequence UNIQUE (session_id, sequence), 
	CONSTRAINT ck_scenes_sequence_nonnegative CHECK (sequence >= 0), 
	CONSTRAINT fk_scenes_session_id_sessions FOREIGN KEY(session_id) REFERENCES sessions (id) ON DELETE CASCADE
)""")

    op.execute("""CREATE TABLE votes (
	id UUID NOT NULL, 
	scene_id UUID NOT NULL, 
	viewer_id UUID NOT NULL, 
	choice INTEGER NOT NULL, 
	cast_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_votes PRIMARY KEY (id), 
	CONSTRAINT uq_vote_scene_viewer UNIQUE (scene_id, viewer_id), 
	CONSTRAINT ck_votes_choice_range CHECK (choice BETWEEN 1 AND 4), 
	CONSTRAINT fk_votes_scene_id_scenes FOREIGN KEY(scene_id) REFERENCES scenes (id) ON DELETE CASCADE, 
	CONSTRAINT fk_votes_viewer_id_viewers FOREIGN KEY(viewer_id) REFERENCES viewers (id) ON DELETE CASCADE
)""")

    op.execute("""CREATE TABLE world_events_pending (
	id UUID NOT NULL, 
	world_id UUID NOT NULL, 
	source_event_id UUID, 
	payload JSONB NOT NULL, 
	status VARCHAR(16) DEFAULT 'pending' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	processed_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_world_events_pending PRIMARY KEY (id), 
	CONSTRAINT ck_world_events_pending_status CHECK (status IN ('pending','applied','rejected')), 
	CONSTRAINT fk_world_events_pending_world_id_worlds FOREIGN KEY(world_id) REFERENCES worlds (id) ON DELETE CASCADE, 
	CONSTRAINT uq_world_events_pending_source_event_id UNIQUE (source_event_id), 
	CONSTRAINT fk_world_events_pending_source_event_id_game_events FOREIGN KEY(source_event_id) REFERENCES game_events (event_id) ON DELETE SET NULL
)""")
    op.execute("""CREATE INDEX ix_world_events_pending_world_status ON world_events_pending (world_id, status)""")



def downgrade() -> None:
    op.drop_table("world_events_pending")
    op.drop_table("votes")
    op.drop_table("scenes")
    op.drop_table("memories")
    op.drop_table("llm_calls")
    op.drop_table("heroes")
    op.drop_table("game_events")
    op.drop_table("viewers")
    op.drop_table("sessions")
    op.drop_table("worlds")
    op.drop_table("oauth_tokens")
    op.drop_table("channels")

    # Leave the shared pgvector extension installed for other database consumers.
