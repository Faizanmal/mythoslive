# Architecture

## System overview

MythosLive is a modular application with a Python/FastAPI backend, PostgreSQL with pgvector, a Next.js streamer dashboard, a Phaser browser overlay, and a browser simulator. Docker Compose provides local orchestration. An optional OpenAI-compatible API supplies bounded narrative flavor; deterministic rules and local content remain authoritative and work without credentials.

## Component boundaries

- **Ingress adapters**: Twitch EventSub WebSocket and simulator HTTP/WebSocket inputs validate their transport payloads and translate them into the same normalized event contract. Twitch OAuth has separate broadcaster and bot roles. The EventSub client owns welcome/keepalive/reconnect/revocation/disconnect handling, deduplication, backoff, and subscription lifecycle.
- **Normalized event pipeline**: applies identity mapping, input validation, rate limits, cooldown checks, moderation/safety policy, and ordering before dispatch to the session engine. Simulator events follow the same path as Twitch events.
- **Deterministic game engine**: owns session state transitions, classes, votes, stat checks, combat, cooldowns, boss phases, XP, cosmetic gold, and world-state changes. It does not delegate numerical decisions to an LLM.
- **Narrative service**: requests bounded scene/proposal text from an OpenAI-compatible endpoint. Validated allowlisted tool calls may propose engine actions; the engine validates and executes them. Failure, timeout, or invalid output falls back to deterministic content/templates.
- **Persistence layer**: SQLAlchemy async repositories and Alembic migrations store durable identities, heroes, sessions, event records, snapshots, chronicles, and consent-aware memory summaries. State-changing events use transactional boundaries where practical. OAuth token columns are encrypted bytes and token encryption requires a configured Fernet key.
- **Streamer dashboard**: Next.js UI for session controls, proposal approval/veto, safety configuration, and telemetry. Admin actions require authenticated authorization and are never exposed to viewers.
- **Overlay**: transparent Phaser scene for OBS Browser Source. It receives only presentation-safe state and never receives OAuth credentials or administrative secrets.
- **Chat output adapter**: sends bot replies through the documented Helix Send Chat Message endpoint with the correct bot/broadcaster relationship, checks `is_sent` and `drop_reason`, and respects documented current limits.
- **Chronicler (Quill)**: optional AI co-host with witty medieval-scribe voice and consent-aware memory; it is not authoritative for game rules and must honor opt-out and retention policy.

## Data flow

1. Twitch notifications and simulator actions are validated at ingress and normalized.
2. The pipeline deduplicates Twitch messages by `metadata.message_id`, applies safety/rate controls, and routes accepted events to the correct world/session.
3. The engine applies deterministic rules and emits state changes plus an event record. Persistence commits state, snapshot, and event log together where practical.
4. The narrative service may receive a minimized, moderated context and return bounded narrative or an allowlisted proposal. The engine validates any proposed action before execution; otherwise deterministic narration is used.
5. Dashboard and overlay read purpose-built views. Viewer chat output is sent through the chat adapter and checked for success/drop reason.
6. Session end creates a Chronicle summary and world-state changes available to the next session. Raw chat is not retained beyond operational need; only short moderated summaries are eligible for memory.

## Normalized event contract

A versioned internal envelope carries: `event_id`, `event_type`, `schema_version`, `occurred_at`, `source` (`twitch` or `simulator`), `world_id`, optional `session_id`, actor identity (`twitch_user_id` where available, display name as untrusted presentation data), and a validated typed `payload`. Twitch transport metadata, including the message ID, is retained only as needed for deduplication/audit policy. Commands become explicit event types such as `viewer.join`, `viewer.class_select`, `viewer.vote`, `hero.attack`, `hero.heal`, `hero.shield`, `hero.special`, `puzzle.answer`, `viewer.opt_out`, and moderator controls. Unknown versions/types, malformed payloads, oversized text, and unauthorized controls are rejected at the boundary.

Engine outputs are versioned typed events/state updates, not free-form instructions. Stage 3 defines the `engine.event` event allowlist and `engine.snapshot` recovery envelope. Engine events are persisted in `game_events`, broadcast over `/api/game/ws/{world_id}`, and available to dashboard clients through `/api/game/events`. A new WebSocket client receives a presentation-safe snapshot before subsequent events; reconnect clients can request another snapshot through `/api/game/state`.

The OBS client uses `/ws/overlay?key=…` and `/api/overlay/snapshot?key=…`. Its key grants read-only access to one world, is returned only once, and is persisted as a SHA-256 hash with a revocation timestamp. The overlay protocol carries monotonically increasing process sequence numbers and state revisions; reconnect always reconciles from a complete current snapshot.

## Session states

The engine supports `LOBBY -> INTRO -> VOTE -> COMBAT -> PUZZLE -> EVENT -> BOSS -> RECAP -> ENDED`, with `PAUSED` reachable from active states. Legal transitions and resume destinations are engine-owned and tested. The deterministic local schedule is 5 seconds for lobby, 4 for intro, 10 for voting, 12 for regular combat, 10 for puzzles, 5 for events, up to 180 for bosses, and 5 for recap. A restart safely places any interrupted active session in `PAUSED`; a moderator can resume it. The simulator's explicit start action can resume its own paused simulation session.

## Stage 3 deterministic game rules

The Python `app.engine` package owns game rules and has no LLM/provider dependency. Twitch and simulator chat both produce the existing versioned `GameEvent` contract and enter `GameEngineService.process_event`; HTTP/WebSocket adapters do not apply game mechanics. A bounded queue, one serial event consumer, and one tick loop per backend process avoid per-viewer tasks. The database's unique input event ID and the snapshot's bounded processed-ID list prevent an input from applying twice.

### Heroes, classes, rewards

Hero identity is a world-scoped viewer identity. Simulator identities use `simulator:` keys and are explicitly not Twitch IDs. Joining creates or restores the durable hero; class selection is permitted in `LOBBY` or `INTRO` and a chosen class cannot be changed during that campaign.

| Class | Starting HP | STR | INT | AGI | END | WIS | CRAFT | CHA | ATK | DEF | MAGIC | SPEED | Passive and special |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Warrior | 130 | 8 | 3 | 4 | 8 | 4 | 4 | 3 | 14 | 8 | 2 | 4 | 20% less incoming damage; whirlwind deals 2x |
| Mage | 85 | 3 | 9 | 5 | 3 | 7 | 5 | 4 | 7 | 3 | 15 | 7 | Spell damage uses magic; arcane burst deals 2.2x |
| Rogue | 95 | 5 | 4 | 9 | 4 | 4 | 6 | 6 | 12 | 4 | 4 | 12 | Seeded 20% critical chance; backstab deals 2.5x |
| Cleric | 105 | 4 | 6 | 4 | 6 | 9 | 4 | 8 | 7 | 6 | 11 | 5 | Stronger heal and revive; special revives a downed ally |
| Bard | 95 | 4 | 5 | 6 | 4 | 5 | 5 | 10 | 8 | 4 | 8 | 7 | Vote weight 2; inspiration heals party and deals 1.7x |

Every level grants the configured class progression in `backend/app/engine/rules.py`. Cumulative XP thresholds sum the rounded per-level curve `round(100 * level^1.5)`; level titles unlock at 5, 10, and 20. Levels 5/10/20 also unlock one named cosmetic. XP is capped at 1,000,000 and cosmetic gold at 100,000; gold is not gameplay power. The initial lock-in and reward values above are the implementation's explicit defaults because the prior architecture had no class-stat or reward table.

### Voting, combat, puzzles, content

Votes have 2–4 scene options, remain open for 10 seconds, and replace the viewer's previous vote in the current scene. Every class weighs one except Bard (two); the tally exposes this rule. Equal tallies break by SHA-256 of session seed, scene ID, and tied choices. The winning option's stat check is seeded from the same session seed, scene, and choice: weighted mean voter stat plus a stable d20, compared with option difficulty. Results are success at difficulty, partial within five points below, otherwise failure.

Regular enemy HP is `min(500, 90 + 12 * joined party size)`. Boss HP is the template HP scaled by 6% per participant, with participant scaling capped at 20 and total HP capped at 1,200. Enemy turns occur every four seconds. Attack/heal/shield/special cooldowns are 1/5/8/15 seconds; the engine caps a session at 1,000 actions and 30 actions per second globally. A combo needs three distinct active users within five seconds. Downed heroes become ghosts; Cleric special revives one ally.

Bosses have three phases at 66% and 33% HP. `shield_wall`, `aoe_charge`, `summon_adds`, `weak_point`, and `enrage` are the only allowlisted mechanics. Riddle answers normalize Unicode, case, punctuation and whitespace; aliases are exact matches, while fuzzy matching uses a conservative 0.90 similarity threshold and only considers answers at least five characters long.

`backend/app/engine/content/emberfall.json` contains 20 original family-friendly scenes, six boss templates and 15 riddles. The scripted engine selects them by stable scene index. It needs no LLM to complete a session.

### Durability, privacy, and Chronicle

Session JSON snapshots are written on accepted input/state changes, transitions and at least every 30 seconds. Hero state, votes, scenes, normalized input/output events, world flags, and end-of-session recap commit in transaction boundaries. `chronicles` is a durable, unique-per-session table and `/api/chronicles` is read-only. `!optout` removes the hero, votes, and memories; anonymizes the viewer record; and retains only a SHA-256 suppression key so the identity cannot immediately rejoin. Public snapshots omit viewer identity keys and cooldown internals.

The dashboard event log and realtime WebSocket use the same typed engine-event stream. If the bounded in-memory broadcast history has rolled over, a WebSocket client receives a fresh presentation-safe snapshot before continuing. The durable database event log and session snapshot survive backend restart.

## Data entities (implemented)

- **World**: persistent campaign identity and world state.
- **Viewer**: Twitch or simulator identity scoped to a world, consent/opt-out status, and retention metadata; no raw chat archive.
- **Hero**: world/user identity, class, deterministic stats, XP, cosmetic-only gold, and unlocked cosmetics.
- **GameSession**: world, lifecycle state, timestamps, configuration, and snapshot reference.
- **GameEvent**: append-oriented normalized/engine event record with schema version, source, actor reference, and minimal payload needed for replay/audit.
- **Session snapshot**: durable JSON checkpoint stored on the `sessions` row for recovery.
- **Vote**: one current vote per viewer per voting round, with deterministic tie-breaking inputs/results.
- **Chronicle**: moderated session summary and resulting world-state changes.
- **Memory**: concise, moderated campaign fact or explicitly consented `viewer_moment`; records use typed kinds, optional pgvector embedding, importance, expiry/archive metadata, and retrieval-use timestamps. Raw chat is not long-term memory. `!memory on` enables personalized memory and `!memory off` disables retrieval; `!optout` deletes the viewer's hero, votes, and personal memories and anonymizes historical references as documented in `privacy-and-memory.md`.
- **Pending proposal**: validated AI suggestion and allowlisted action payload stored in `world_events_pending`; streamer decisions are recorded in the dashboard audit log.
- **OAuthToken**: encrypted broadcaster/bot token material with scopes/expiry/role separation; never returned to viewers or logged.

The initial foundation schema creates `channels`, `oauth_tokens`, `worlds`, `viewers`, `heroes`, `sessions`, `scenes`, `votes`, `game_events`, `world_events_pending`, `memories`, and `llm_calls`, with foreign keys, uniqueness, indexes, timestamps, and constraints. OAuth access/refresh tokens are stored only in `BYTEA` encrypted by the Fernet abstraction. No tokens are seeded. Memory embeddings use pgvector's unconstrained `VECTOR` type by default. Set `EMBEDDING_DIMENSION` to a positive integer to constrain the migration to `VECTOR(n)` once a model is selected; runtime rejects a different vector dimension. Retention and deletion details are in `privacy-and-memory.md`.

## Release deployment status

Compose is a local development/judge configuration, not a production deployment. It uses local database storage, local simulator login, and localhost origin defaults. No production Compose profile, hosted deployment, public OAuth callback, or reverse-proxy configuration is included. The judge seed creates simulated Emberfall records and must not be represented as real Twitch viewer history.

Implemented integration code is not live-service verification: a real Twitch channel and external AI provider were not exercised in release packaging. Follow/raid effects exist; subscription/gift, cheer, Channel Points reward lifecycle, and native poll integrations remain disabled/unavailable. CPU/RSS event benchmarks in the codex log are isolated rules-engine microbenchmarks, not end-to-end user capacity claims.

## Trust and safety boundaries

- Treat all viewer text, display names, simulator fields, model output, and browser input as untrusted.
- Fence chat as data; never merge it into system/developer instructions.
- Validate typed payloads and bound text length; enforce per-viewer/channel limits and command cooldowns.
- Keep engine rules deterministic and allowlist every AI-callable tool. AI output is a proposal, not authority.
- Keep OAuth tokens encrypted at rest and out of logs, browser payloads, overlays, and viewer-visible errors. Protect overlay secrets and dashboard controls separately.
- Use the bot user token for `channel.chat.message` and broadcaster authorization for follow/raid subscriptions according to the current subscription scope and condition requirements. The implementation notes record the verified Twitch-specific token roles and sources.
- Optional Twitch subscriptions must be feature-flagged. Eligibility or permission failures warn and disable only that feature.
- `!optout` must delete or anonymize the viewer's hero and associated memories according to the documented retention design.
- Apply accessible typography, clear streamer controls, safety settings, proposal approval/veto, and telemetry without exposing internal actions.
