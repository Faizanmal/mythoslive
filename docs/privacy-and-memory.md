# Privacy, consent, and campaign memory

MythosLive does not store raw chat transcripts as long-term memory. The ingress repository removes ordinary chat text and `!lore`/`!quill` arguments before writing input events. A bounded in-memory digest is used for current-session themes; it is cleared at recap and on `!optout`.

## Viewer consent

- Personalization is off by default (`viewers.memory_consent = false`). A viewer who has joined can explicitly opt in with `!memory on`; `!memory off` immediately stops retrieval while preserving the records until deletion or expiry.
- Only a consented viewer can receive `viewer_moment` records. Personal memories are written from durable engine facts, such as a successful session join and the hero's recorded level. The model cannot select a viewer or submit a raw database ID.
- `!optout` overrides consent, cancels pending AI work for that world, blocks queued Quill personalization, deletes the viewer's hero, votes, and viewer-scoped memories, clears their identity from session snapshots and event references, and stores only a one-way suppression hash so the opted-out identity cannot immediately rejoin. It removes campaign memories containing the display name and redacts matching text in historical narrative records. A generic Quill confirmation is sent only after the deletion transaction commits.
- Simulator-originated commands are labelled simulated and cannot enter Quill's Twitch outbox. Simulator viewers are never described as real Twitch viewers.

## Memory records and retrieval

`memories` stores: `world_id`, optional `viewer_id`, `kind`, concise `content`, `importance`, embedding/model, consent status, `created_at`, `last_used_at`, `use_count`, optional expiry, and archive timestamp. Allowed kinds are `world_fact`, `session_summary`, `viewer_moment`, `inside_joke`, `npc`, `location`, and `quest`.

The Director's strict `remember_fact` tool can save only moderated world facts, NPCs, locations, or quests from the model's allowlist. Session summaries and personal moments are generated from persisted engine/Chronicle facts. Potential running jokes are considered only from repeated, unique, locally and provider-moderated digest samples, and require a campaign-topic anchor; raw samples are never written as a memory.

When `AI_EMBEDDING_MODEL` is enabled, set `EMBEDDING_DIMENSION` to that model's documented output dimension. The service checks every vector's length and finite values before storing or querying it; mismatches are rejected and logged with configured/received dimensions. To avoid incompatible pgvector rows, do not change model or dimension without re-embedding or clearing old vectors. If embedding is unavailable, retrieval falls back to importance and recency and the game continues.

Retrieval is scoped to the current world, campaign-wide consented facts, and viewers whose explicit consent remains enabled. Ranking combines cosine similarity, importance, and recency, then caps each kind and removes highly similar vectors/text. At most `MEMORY_CONTEXT_LIMIT` bounded records enter a model context. Successful retrieval updates `last_used_at` and `use_count`.

## Retention and archive policy

- Personal `viewer_moment` records expire after 365 days; aggregated `inside_joke` records expire after 60 days.
- Memories with importance below `0.2` and age above 30 days are archived and excluded from retrieval. Expired records are likewise excluded and archived when memory retrieval or writes run.
- Other campaign memories remain until archived by that rule, removed by `!optout` if they contain the opted-out viewer's name, or removed with their world. Historical redaction is a best-effort string replacement and cannot identify personal information never linked to the stored identity.
- Opt-out is the immediate deletion path for all viewer-associated memory and hero data. `!memory off` is a reversible retrieval preference and is not a deletion request.

## Quill the Chronicler

Quill greets selected `!join` events, answers `!hero`/`!me`, reads `!lore` from Emberfall canon, responds to `!quill`, and reacts to a small set of milestones. It uses one bounded coalescing worker, a per-user cooldown (`QUILL_USER_COOLDOWN_SECONDS`), a per-world global cap (`QUILL_GLOBAL_MESSAGES_PER_MINUTE`), and the existing priority `ChatOutbox` limits/metrics. It writes to Twitch only when the streamer has explicitly enabled bot chat. Generated `!quill` output requires input and output moderation; otherwise a fixed, concise fallback is used.

A returning callback is emitted only from a retrieved `viewer_moment` record belonging to that consenting viewer. Quill quotes the stored fact rather than inventing a past action. The new-session "Previously on MythosLive" ribbon uses the persisted Chronicle and canonical world flags; it also works with no model or embedding key.

## Limits

Dashboard consent, Quill, and memory status are operationally tied to the current backend process and database. The memory feature has not been exercised against a live PostgreSQL/pgvector server or a configured embedding/moderation provider in this environment. Provider pricing, moderation quality, and the configured embedding model's published dimension must be verified by the operator before enabling those services.
