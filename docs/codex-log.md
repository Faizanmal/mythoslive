# Codex Work Log

## Stage 0 — Repository guidance and architecture

- Inspected the workspace: empty; no existing manifests, lockfiles, or application code.
- Inspected runtimes: `python` 3.13.1, `py` 3.14.3, Node.js 26.5.0, npm 12.0.1; `pnpm`, Docker, and `uv` were not found. Python 3.12 was not available through inspected launchers.
- Created repository guidance, architecture and stage plan, placeholder environment file, ignore rules, and README.
- No app features, dependencies, tests, integrations, or services were scaffolded in this stage.

## Stage 1 — Scaffold and foundations

### Implemented

- FastAPI app with lifespan-managed async SQLAlchemy engine, settings, JSON logging, local CORS, `/healthz`, `/readyz`, and health repository/service boundary.
- Alembic initial migration for `channels`, `oauth_tokens`, `worlds`, `viewers`, `heroes`, `sessions`, `scenes`, `votes`, `game_events`, `world_events_pending`, `memories`, and `llm_calls`; includes foreign keys, indexes, uniqueness, timestamps, and constraints.
- Fernet token-encryption abstraction. OAuth fields are byte columns; no tokens or encryption key were added.
- pgvector migration dimension is configurable via `EMBEDDING_DIMENSION`; unset means unconstrained `VECTOR`. A positive value creates `VECTOR(n)`.
- Pydantic normalized event, snapshot, and versioned realtime contracts. A generator writes frontend TypeScript contracts from the backend schemas and a test checks for drift.
- Next.js App Router, TypeScript, Tailwind v4, shadcn/ui component configuration/button foundation, Zod API validation/client, Zustand store, requested placeholder routes, and a transparent responsive 16:9 Phaser overlay scene.
- Compose services for PostgreSQL/pgvector, backend, and frontend with health checks, persistent database volume, migration-on-backend-start, and documented ports/startup order. `Makefile` targets are present.
- `.env.example` has placeholders only; `.env` is ignored. Demo seed creates a local channel/world; simulator CLI remains a placeholder.

### Commands and results

- `npm create next-app@latest frontend -- --typescript --tailwind --eslint --app --src-dir --import-alias "@/*" --use-npm --no-install --yes` — **blocked**: npm returned `ENOTCACHED` for `create-next-app`; `NPM_CONFIG_OFFLINE=true` and no cached generator. Created the Next foundation directly.
- `npm install --package-lock-only --offline --ignore-scripts` (from `frontend/`) — **blocked**: npm returned `ENOTCACHED` for `@tailwindcss/postcss`; no lockfile could be created offline.
- `python -m compileall -q app scripts alembic tests` (from `backend/`) — **passed**.
- `python -m ruff format app tests scripts` and `python -m ruff check app tests scripts` (from `backend/`) — **passed** (`All checks passed!`).
- `python scripts/generate_ts_contracts.py` (from `backend/`) — **passed**, generated `frontend/src/lib/contracts.generated.ts`.
- `python -m pytest -q -p no:cacheprovider` (from `backend/`, Python 3.13.1 environment) — **6 passed, 1 skipped**. The PostgreSQL connectivity/migration integration test skipped because `DATABASE_URL` was not configured and Docker's database was unavailable. Python 3.12.8 is installed, but its environment has no project dependencies installed.
- `$env:EMBEDDING_DIMENSION='768'; python -m alembic upgrade head --sql` (from `backend/`) — **passed**; offline SQL contains `embedding VECTOR(768)`.
- `docker compose config --quiet` — **passed**.
- `docker compose up --build` — **blocked**: Docker Desktop Linux engine pipe was unavailable (`permission denied while trying to connect to the docker API`).
- `npm run typecheck` — **blocked**: `tsc` is not installed; node modules were not installed.
- `npm run build` — **blocked**: `next` is not installed; node modules were not installed.
- `npm run lint` — **blocked**: `eslint` is not installed; node modules were not installed.
- `make test` — **blocked**: GNU Make is not installed in the host environment.

### Known gaps

- No npm lockfile could be generated while npm is offline. The manifest selects npm after confirming there was no preexisting lockfile.
- Compose build/start, live database migration/connectivity, frontend typecheck/build, route loading, and Phaser browser-console verification need Docker Desktop running and frontend dependencies installed.
- No Twitch OAuth, AI integration, or game mechanics were implemented in this stage.

## Stage 2 — Real Twitch connectivity and normalized chat ingress

### Implemented

- Verified current Twitch OAuth, token validation/refresh/revoke, scopes, EventSub subscription versions and WebSocket handover, Helix Send Chat Message response/rate headers, and chat rate limits against official Twitch Developer Documentation. Source URLs and deliberate differences from older planning assumptions are recorded in `docs/twitch-implementation-notes.md`.
- Added separate state-bound broadcaster and bot Authorization Code flows, exact configured callbacks, user-token validation, scope and identity checks, Fernet-encrypted token storage, serialized refresh with rotated-token persistence, revoke/disconnect handling, and hourly validation.
- Added a resilient WebSocket EventSub manager with welcome, notification, keepalive deadline, reconnect handover, fresh-session resubscription, bounded retry/backoff, revocation/degraded status, bounded message-ID dedupe, and chat/follow/raid normalization.
- Added typed Helix calls, one-time 401 refresh/retry, explicit 429 delay handling, message send response inspection, a priority outbox with ordered batch enqueue, conservative limits, drop/queue metrics, and explicit default-off sending. Simulator events cannot enter the outbox.
- Added case-insensitive command parsing/validation, moderator checks, bot self-filter, user/global throttles, and normalized command or ordinary chat events without game effects.
- Added simulator APIs and fake-chat UI using the same ingress event model, plus `/dashboard/connect` status, scopes, EventSub subscription/keepalive health, OBS URL copy, disconnect actions, and explicit test-send controls.
- Added OAuth refresh/state/scope/encryption tests; EventSub welcome, keepalive, notification, duplicate, reconnect handover and revocation fixtures; parser/permission/bot filtering, simulator parity, and Helix/outbox tests.
- Added operator setup steps and requirements in `docs/twitch-setup.md`. No real Twitch credentials or tokens are stored.

### Commands and results

- `python scripts/generate_ts_contracts.py` (from `backend/`) — **passed**; regenerated the TypeScript contracts from canonical Pydantic models.
- `python -m ruff format app scripts tests` (from `backend/`) — **passed**, 41 files unchanged on final run.
- `python -m ruff check app scripts tests` (from `backend/`) — **passed**.
- `python -m compileall -q app scripts alembic tests` (from `backend/`) — **passed**.
- `python -m pytest -q -p no:cacheprovider` (from `backend/`) — **21 passed, 1 skipped**. PostgreSQL connectivity/fresh database integration is skipped because no usable `DATABASE_URL` is configured.
- `python -m alembic upgrade head --sql` (from `backend/`) — **passed**; generated SQL includes both `0001_initial_schema` and `0002_oauth_twitch_user_id`. This is offline SQL generation, not an applied database migration.
- `docker compose config --quiet` — **passed**.
- `docker compose up --build` — **blocked**; Docker Desktop Linux engine pipe returned `permission denied while trying to connect to the docker API`.
- `npm run typecheck` (from `frontend/`) — **blocked**; `tsc` is not installed because frontend dependencies are absent.
- `npm run build` (from `frontend/`) — **blocked**; `next` is not installed because frontend dependencies are absent.
- `make test` — **blocked**; GNU Make is not installed in the host environment.
- Confirmed `Test-Path .env` returns `False`; no local secret file is present.

### Known gaps and account limitations

- OAuth consent, channel bot authorization, actual EventSub delivery, real `!join` ingress, Helix chat send, dashboard browser behavior, `/overlay` transparency, and Phaser console behavior were not live-verified because Twitch credentials are absent and Docker Desktop is unavailable.
- Frontend typecheck/build could not run because npm dependencies are not installed and the earlier Stage 1 package installation was blocked by offline npm cache. Run `npm install` (or `docker compose up --build` with Docker/network available) before frontend release.
- The database migration was validated as generated SQL, not executed against a fresh PostgreSQL/pgvector instance in this environment.
- Twitch account-specific permissions are checked during OAuth. Bot authorization for the broadcaster needs broadcaster `channel:bot` approval or moderator status; core chat/follow/raid do not require Affiliate/Partner status. Twitch's docs currently report chatbot verification reviews paused. Multi-process deployments need shared OAuth state/refresh locking; the local Stage 2 setup expects one backend worker.
- No Stage 3/gameplay mechanics were implemented.

## Stage 3 — Deterministic game engine

### Implemented

- Added `backend/app/engine` with explicit session state legality, snapshot restore, seeded voting/stat checks, class progression, combat, cooldowns, boss phases, puzzles, rewards, opt-out handling, and Chronicle generation. Numerical rules are deterministic and do not call an LLM.
- Routed normalized Twitch and simulator `GameEvent` inputs into the same serial engine processor. The engine uses a bounded input queue and one controlled tick loop; event IDs are unique in persistence and retained in bounded state history for idempotency.
- Added transaction-backed state/snapshot/event persistence and migration `0003_engine_chronicle`, including world-scoped simulator/Twitch viewer identities and durable Chronicle rows. Interrupted active sessions recover paused.
- Added typed realtime event and snapshot contracts, a reconnect snapshot and event API/WebSocket, and dashboard event log consuming the engine stream. Public snapshots exclude identity, cooldown, and riddle answer internals.
- Added original Emberfall content (20 scenes, 6 boss templates, 15 riddles) and a seeded 15-person simulator CLI. Added package data configuration for the content JSON.
- Documented concrete class stats, progression, vote weights/ties, action limits, enemy scaling, boss allowlist, fuzzy answer threshold, and content defaults in `docs/architecture.md`; these are implementation defaults where earlier docs did not define values.
- Added engine rules, content, persistence/idempotency, contract generation, and migration coverage.

### Commands and results

- `python -m ruff format app scripts tests` (from `backend/`) — **passed**; 51 files unchanged.
- `python -m ruff check --fix app scripts tests` followed by `python -m ruff check app scripts tests` (from `backend/`) — **passed**; corrected one import ordering issue.
- `python -m compileall -q app scripts alembic tests` (from `backend/`) — **passed**.
- `python -m pytest -q -p no:cacheprovider` (from `backend/`) — **32 passed, 1 skipped**. The PostgreSQL migration and repository integration test skipped because there is no configured database.
- `python scripts/generate_ts_contracts.py` (from `backend/`) — **passed**; regenerated `frontend/src/lib/contracts.generated.ts` from backend Pydantic contracts.
- `docker compose config --quiet` — **passed**.
- `python -m alembic upgrade head --sql` (from `backend/`) — **passed**; generated offline SQL through `0003_engine_chronicle`. This validates migration generation, not execution against PostgreSQL.
- `make sim` / `python -m scripts.sim` — **not run** because full simulator requires PostgreSQL and Docker Desktop is unavailable in this environment. The seeded full-session rules path is covered by the unit suite.
- `docker compose up --build`, frontend typecheck/build, and browser checks — **not run**; Docker engine is unavailable and npm dependencies are not installed (offline cache lacked the Next.js toolchain in Stage 1).

### Known gaps

- Fresh PostgreSQL migration, durable restart round-trip, API database smoke checks, and the CLI end-to-end simulator remain unverified until PostgreSQL is available. The test that exercises the repository against a fresh database is skipped without `DATABASE_URL`.
- Frontend TypeScript/build validation and live dashboard/overlay browser behavior remain unverified because dependencies and Docker are unavailable. No Phaser overlay work was done, as requested.
- No Stage 4 work (LLM integration or Phaser overlay) was started.

## Stage 4 — Visual Phaser overlay

### Implemented

- Replaced the empty Phaser stage with a transparent 1920×1080 scene that scales to OBS 16:9, targets 30 FPS, and switches among boot/preload, world, boss, and Chronicle Phaser scenes. The world uses original vector tiles/characters and supports optional local sprite sheets via `frontend/public/assets/kenney/asset-manifest.json`; no artwork was downloaded. Optional pack sources and CC0 credits are in `docs/asset-credits.md`.
- Added a responsive overlay HUD for location, animated vote bars/timer, narration typewriter, short-lived follow/raid/level-up/world-event toasts, Twitch chat-color nameplates, valid commands, party status, puzzle question, boss phases/telegraph/health/combo, Chronicle highlights/MVPs/level-ups/party cosmetic gold/cliffhanger, and `+N` party overflow after 40 sprites. Damage numbers are pooled and vote tally changes do not recreate hero sprites.
- Added a Zod-validated WebSocket client for `/ws/overlay`, sequence/revision filtering, bounded exponential reconnect, and an authoritative `/api/overlay/snapshot` fetch on reconnect. The overlay accepts `?layout=bottom|right|full` and `?debug=1`.
- Added hashed, world-scoped, revocable overlay keys, migration `0004_overlay_access_keys`, dashboard create/rotate/revoke controls, copyable Browser Source URL, and a dashboard mini-preview. The route only permits read-only snapshot/event access; no OAuth credentials are included.
- Documented Browser Source settings and local verification steps in `docs/obs-setup.md`.

### Commands and results

- `python scripts/generate_ts_contracts.py` (from `backend/`) — **passed**, generated the new sequence fields in TypeScript contracts.
- `python -m ruff format app scripts tests`, `python -m ruff check app scripts tests`, and `python -m compileall -q app scripts alembic tests` (from `backend/`) — **passed** after auto-fixing one import-order issue.
- `python -m alembic upgrade head --sql` (from `backend/`) — **passed**; generated SQL through `0004_overlay_access_keys`. This did not apply migrations to PostgreSQL.
- `python -m pytest -q -p no:cacheprovider` (from `backend/`) — **32 passed, 1 skipped**. The PostgreSQL migration/overlay-key persistence integration test is skipped without `DATABASE_URL`.
- `docker compose config --quiet` — **passed**; Compose configuration was unchanged in this stage.
- `npm run typecheck` (from `frontend/`) — **blocked** because `tsc` is not installed.
- `npm run build` (from `frontend/`) — **blocked** because `next` is not installed.
- Browser/OBS preview, Phaser console, transparent capture, and `make sim` live overlay flow — **not verified**; frontend dependencies are absent and Docker Desktop's database engine is unavailable in this environment.

### Known gaps

- Optional Kenney sprites are not present, so the overlay currently uses local vector artwork. When the owner places the two CC0 packs locally and supplies the documented manifest, Phaser loads the configured local tile/hero sheets; otherwise development mode shows a fallback notice.
- Frontend type errors, scene rendering, browser reconnect behavior, actual OBS transparency, and 1280×720 visual fit still need an installed frontend toolchain and browser/OBS run. No LLM work was started.

## Stage 5 — Optional AI Game Master

### Implemented

- Added an asynchronous OpenAI-compatible Chat Completions, Moderations, and Embeddings client configured by environment variables, with strict request timeouts, bounded jittered retries, cancellation, circuit breaking, and secret-safe telemetry.
- Added strict Pydantic tool schemas for the ten requested tools. Tool IDs and mechanics are checked against the local Emberfall deck and engine allowlists; rewards use fixed tiers and are only accepted in EVENT. Scene flavor generation is triggered by the live `scene_started` event during VOTE and can only change the current scene text, not choices, timers, or vote outcomes.
- Kept phase changes, vote results, combat, cooldowns, numeric rewards, and session completion in the deterministic engine. Added transactional preference/reward persistence and limited world-event effects to known flags.
- Added bounded per-world chat digests, prompt-injection fencing, chat moderation before any player samples enter the model prompt, viewer-name redaction in recap/memory context, output moderation, and fail-closed output handling. Without a moderation model or when the provider is unavailable, model text is dropped and canned template narration is used.
- Added required streamer approval for consequential world-event proposals, a safe allowlisted `auto_safe` mode, runtime tone/family-friendly/banned-topic controls, `/api/ai` health/settings/review routes, and `/dashboard/ai` status and approval controls.
- Added per-session token budget and configurable estimated cost accounting. Cost estimates require provider-specific input/output rates; rates default to zero. Added `docs/ai-safety.md` with authority boundaries, privacy, fallback behavior, configuration, and known limits.
- Added AI safety/client tests for strict tool validation, unknown IDs, injection fencing, name redaction, invalid credentials, malformed responses, rate limits, timeouts, moderation rejection, circuit breaking, budget fallback, and engine-only numerical mutation.

### Commands and results

- `python -m ruff format app tests` (from `backend/`) — **passed**.
- `python -m ruff check app tests` (from `backend/`) — **passed**.
- `python -m compileall -q app tests` (from `backend/`) — **passed**.
- `python -m pytest -q -p no:cacheprovider` (from `backend/`) — **44 passed, 1 skipped**. PostgreSQL integration is skipped because no database URL/server is available.
- `python -m alembic upgrade head --sql` (from `backend/`) — **passed**; generated SQL through `0004_overlay_access_keys`. No Stage 5 database migration was required; estimated cost is recorded in the existing LLM metadata JSON.
- `docker compose config --quiet` — **passed**.
- `docker compose up --build` (also retried with `-d`) — **blocked**: Docker Desktop's Linux engine pipe returned `permission denied` (`npipe:////./pipe/dockerDesktopLinuxEngine`).
- `make test` — **blocked**: GNU Make is not installed in this PowerShell environment.
- `npm run typecheck` (from `frontend/`) — **blocked**: `tsc` is not installed; `npm run build` is **blocked**: `next` is not installed.
- Secret-pattern scan of backend source/tests, frontend source, docs, Compose, and `.env.example` — **no matches**; `.env` is listed in `.gitignore` and no workspace `.env` file is present.

### Known gaps

- A live provider/key/model was not configured, so live AI-generated scenes, moderation behavior, provider pricing, and end-to-end simulator narration were not exercised. With the default missing configuration, the simulator continues using the deterministic deck and canned narrator.
- Full Compose startup, database-backed migration/restart checks, and frontend typecheck/build remain unverified because Docker engine access and the local Next.js toolchain are unavailable. Browser dashboard verification was not possible.
- Dashboard AI safety controls are process-local and revert to environment defaults after backend restart. Accurate cost budgeting requires setting the selected provider's per-million token rates.
- No work beyond Stage 5 was started during that stage.

## Stage 6 — Consent-aware memory and Quill

### Implemented

- Added migration `0005_consent_chronicler_memory` with per-viewer memory consent, typed memory kinds, importance, use tracking, archive timestamps and content/range constraints. Existing viewer-scoped memories are made non-consented by the migration.
- Added bounded pgvector memory writes/retrieval, runtime vector dimension checks, similarity/importance/recency ranking, diversity limits and duplicate filtering. Without embeddings, retrieval falls back to importance and recency.
- Added `!memory on|off`; `!optout` clears the viewer's hero, votes and memories, anonymizes historical identity references, suppresses future personalization and blocks queued Quill callbacks.
- Added session summaries and consented viewer moments derived from Chronicle/engine records, moderated digest-only running-joke candidates, expiry/archive rules, and a deterministic “Previously on MythosLive” opening.
- Added Quill's bounded Twitch-only co-host queue, factual memory-backed returning greetings, hero sheets, canon lore, selected event reactions, cooldowns and existing outbox enforcement. Simulator events cannot reach the Twitch outbox.
- Added `docs/privacy-and-memory.md`, updated the memory architecture section, and covered embedding mismatch, retrieval diversity, consented callback, cooldown, opt-out, persistent recap lookup and deletion in tests.

### Commands and results

- `python -m ruff format app tests` and `python -m ruff check app tests` (from `backend/`) — **passed**.
- `python -m compileall -q app tests` (from `backend/`) — **passed**.
- `python -m pytest -q -p no:cacheprovider` (from `backend/`, `DATABASE_URL` loaded in-process from `.env`) — **50 passed, 0 skipped** against PostgreSQL/pgvector. The DB integration validated migration head, extension/tables/columns, input idempotency, consented memory retrieval, Session A recap lookup after Session B starts, and opt-out deletion/no retrieval. One Alembic config deprecation warning remains (`path_separator`).
- First DB test attempts found and fixed a closed-connection inspection bug and an overlength fixture broadcaster ID. Final rerun passed.
- `.env` `TokenCipher` encrypt/decrypt check — **passed**; no secret values were printed.
- `docker compose config --quiet` — **passed**.
- Compose DB started healthy with a temporary untracked host port override (`15432:5432`) because Windows denied binding host port 5432. The DB URL was adjusted only inside the verification process. The persistent `postgres-data` volume remains local.
- Full `docker compose up --build -d` — images built, but Docker stalled during frontend image unpack and returned HTTP 500 on a subsequent container listing; the build/start command was interrupted. Backend/frontend `/healthz`, `/readyz`, and route smoke checks are therefore **not verified**.
- Frontend dependency install resolved 368 packages; npm reported **16 moderate audit findings**. No dependency upgrade was applied. Direct host `npm run typecheck`/`npm run build` remain unavailable because packages are installed inside the Docker build context, not the host workspace.

### Known gaps

- Live embeddings/moderation and real Twitch were not configured or called. Runtime dimension validation is unit-tested, but no provider vector was generated.
- The DB-backed consent, opt-out, and recap continuity tests pass. End-to-end Quill narration through a running backend/frontend stack remains unverified due to the Docker image unpack/daemon error.
- Frontend typecheck/build, browser/OBS behavior, and health endpoint checks still require a successful full Compose start.
- After adding DB test-row cleanup, a targeted rerun could not reconnect because Docker Desktop reported it could not start and the temporary host DB port refused connections. The full 50-test DB-backed run immediately before that cleanup addition passed; latest host-only suite is **49 passed, 1 DB test skipped**.

## Stage 7 — Streamer control room

### Implemented

- Added `0006_streamer_control_room`: per-world dashboard config, append-only broadcaster audit rows, viewer mute flag, and pending world-event expiry. Proposal decisions and allowlisted canonical flag changes are transactional.
- Added signed broadcaster session cookies with secure/HttpOnly/SameSite attributes, CSRF double-submit validation for state-changing APIs, exact configured-origin checks, and server-derived world ownership. Local simulator login is development-only and localhost-only; simulator mutation APIs require the simulator principal. Overlay keys remain separately scoped and read-only.
- Replaced the dashboard event-log placeholder with responsive Live, Session, Approvals, Director Notes, World Codex, Safety, Eligibility and Telemetry screens. Added reconnecting, Zod-validated versioned dashboard WebSocket handling with snapshot reconciliation plus periodic polling.
- Added panic pause/resume controls and keyboard shortcuts that ignore form focus. Pause uses the deterministic engine path, is audited, and shows a neutralizing pause screen on the overlay. Approval/veto/edit, config changes, viewer controls, memory deletion and session transitions are audited.
- Persisted bounded streamer notes and added them to the next Director context as explicitly untrusted input. Pending proposals expire after five minutes and default to no canonical change; approved allowlisted changes broadcast an overlay toast.
- Added a dashboard auth/CSRF, request-contract, and Director-notes fencing unit-test file; extended the DB migration assertion for revision 0006.
- Added `docs/dashboard.md` covering security, screens, local simulator access, operations and known limits.

### Commands and results

- `python -m compileall -q app tests` (from `backend/`, Python 3.13 host toolchain) — **passed**; `py -3.12 -m compileall -q app tests` — **passed**.
- `docker compose config --quiet` — **passed**.
- `python -m pytest -q -p no:cacheprovider` (from `backend/`, Python 3.13 host toolchain) — **53 passed, 1 skipped**. PostgreSQL migration/authorization integration is skipped because `DATABASE_URL` is unavailable.
- `ruff check app tests` and `ruff format --check app tests` (from `backend/`) — **passed**. FastAPI API modules ignore Ruff B008 for standard dependency injection in endpoint parameter defaults.
- `alembic upgrade head --sql` (from `backend/`) — **passed**; generated SQL through `0006_streamer_control_room`, not applied to a live DB.
- `npm run typecheck` and `npm run build` (from `frontend/`) — **blocked**: `tsc` and `next` are unavailable in the host workspace.
- `docker info` — **blocked**: Docker Desktop Linux engine pipe returned `permission denied` (`npipe:////./pipe/dockerDesktopLinuxEngine`). Therefore live migration, API, DB-backed authorization, simulator acceptance, and Compose/browser tests could not run.
- No Twitch or LLM provider was contacted. No secrets were added to tracked files.

### Known gaps

- Full database-backed approval/audit, cross-channel authorization, and panic pause/resume integration assertions are present in the PostgreSQL migration test but remain unexecuted because no `DATABASE_URL`/PostgreSQL server is available. The host pytest suite passed 53 tests and skipped that integration test.
- Typecheck, production build, browser console, WebSocket reconnect, and tablet layout remain unverified because the host lacks frontend dependencies and Docker is unavailable.
- Session duration is displayed as a target, not a hard timer. Current message/min telemetry is accepted count per process uptime. Runtime configuration is loaded from the active broadcaster world (or simulator world) on startup.
- Feature eligibility is conservative: subscription/channel-points features remain unavailable unless verified; Affiliate/Partner status is not inferred from OAuth scopes alone.
## Stage 8 — Twitch-native events and experience polish (2026-11-02)

### Implemented

- Added capped follow effects: each accepted follow lights one of 12 torches, shows a visible event toast, and adds one of at most 3 morale points. Morale grants a transparent bonus to the next deterministic vote check and is then consumed.
- Added matching Phaser torch flames and overlay counters for torch, morale, and active reinforcement state; the torch map only redraws when its torch count changes.
- Added bounded incoming-raid squads: reported audience is clamped to 10,000, squad size to 4, active reinforcements to 12 units/3 squads, and lifetime to 90 seconds. Reinforcements contribute at most 8 damage per player action; they create no hero rows or open-ended reward grants. EventSub message IDs remain deduplicated, with engine idempotency also covered.
- Added simulator-only follow and raid fixture controls. They emit normalized `GameEvent` records through the same recorder and engine path; labels include `[SIM]` and there is no Twitch outbox dependency.
- Added a shareable public `/chronicle/[id]` client page with schema validation, key moments, MVP categories, cliffhanger, and native share/copy. It renders selected recap fields only and has no transcript/token fields.
- Reworked the landing page around a sample Emberfall campaign and simulator CTA. Added critical hit-stop/flash/shake, boss and Chronicle arrival animations, plus follow/raid toast presentation.
- Expanded feature eligibility status for core raids/follows and optional subscriptions, Channel Points, Cheers, and native polls. Optional event families stay disabled in this release; chat votes remain the default. Twitch references and feature decisions are recorded in `docs/twitch-implementation-notes.md`.
- Added `backend/scripts/load_profile.py`, a repeatable deterministic-engine profile at increasing simulated participant counts.

### Verification

- `docker compose run --rm --no-deps -e DATABASE_URL=postgresql+asyncpg://mythos@172.25.0.2:5432/mythoslive backend python -m pytest -q` — **58 passed** against the final workspace source, including migration/database integration, follow/raid caps and dedupe, zero-viewer raid, simulator/Twitch raid event shape, and EventSub handover followed by a notification. One existing Alembic `path_separator` deprecation warning.
- `docker compose run --rm --no-deps backend ruff check app tests scripts` — **passed**.
- `python -m ruff check backend/app backend/tests backend/scripts` — **passed** after the final test import-order adjustment.
- `docker compose run --rm --no-deps frontend npm run typecheck` — **passed**.
- `docker compose run --rm --no-deps frontend npm run build` — **passed**; routes `/`, `/overlay`, `/sim`, `/dashboard`, `/dashboard/connect`, and `/chronicle/[id]` compiled.
- Local HTTP smoke checks: `/healthz` returned `{"status":"ok"}` and `/readyz` returned `{"status":"ready","database":"ok"}`. Frontend HTTP GET for `/`, `/sim`, `/chronicle/<id>`, `/overlay` each returned **200**. A headless Edge check was attempted, but the sandbox denied browser process/cache access; browser console, OBS alpha compositing, and live Phaser FPS therefore remain unverified.
- `docker compose run --rm --no-deps backend python -m scripts.load_profile` (Python 3.12 container, 8 passes): 15 participants / 120 events: **9,660.5 events/s**, 0.0125 CPU seconds, 35.2 MB peak RSS; 50 / 400: **9,207.7 events/s**, 0.0434 CPU seconds, 35.2 MB; 100 / 800: **6,144.6 events/s**, 0.1293 CPU seconds, 35.2 MB; 250 / 2,000: **2,912.6 events/s**, 0.6862 CPU seconds, 35.2 MB. These are single-process rules-engine microbenchmarks, not end-to-end capacity measurements. No 300-viewer support claim is made.
- WebSocket network latency and overlay FPS: **not measured**. Available reconnect/EventSub and overlay snapshot reconciliation tests remain automated; browser-level disconnect/reload measurement needs a browser harness.
- Real Twitch follow/raid delivery: **not exercised**. The local database had zero OAuth-token rows, and no test-channel authorization was provided. Simulator fixtures verified the same effects. Account eligibility/scopes are documented; actual follow requires broadcaster consent with `moderator:read:followers`, while incoming raid has no event scope. Optional event eligibility is platform/account dependent and remains unavailable until deliberately implemented and authorized.
- Audio and volume control: **not added** because no user-provided or locally present sound assets were found; no assets were downloaded. Existing local art fallback remains active.

### Known gaps

- The initial attempt to bind PostgreSQL on host port 5432 failed in this Windows environment; the active healthy Compose stack now publishes it on port 5433. Earlier database tests used the Compose network address `172.25.0.2`.
- Docker Desktop briefly stopped responding after the long builds/tests. It was restarted and the current Compose DB/API/frontend containers are healthy. Current `docker compose ps`: `mythoslive-db-1`, `mythoslive-backend-1`, and `mythoslive-frontend-1`, all `healthy`. Current smoke checks: `/healthz` is `ok`, `/readyz` is `ready/ok`; landing, simulator, overlay, and Chronicle routes return HTTP 200.
- Twitch optional subscriptions, Channel Points reward lifecycle, Cheers and poll mirroring are documented but disabled. No custom Twitch reward is created, so there is no creator-Client-ID redemption state to reconcile.
- CPU/RSS/throughput figures omit database queries, WebSocket fanout, browser rendering and OBS. WebSocket latency, Phaser FPS, browser console errors, actual Twitch disconnect during a live channel session, and real-channel effects remain unmeasured.

## Stage 9 — Release hardening and judge packaging (2026-11-03)

### Implemented

- Replaced the stale foundation-only README with the implemented feature set, architecture diagram, quickstart, ports/startup ordering, environment reference, privacy/safety summary, Twitch/OBS links, and explicit live-service limitations. Added `docs/judge-quickstart.md` and `docs/submission-support.md` with an offline simulator path, draft Devpost description, 2:45–2:58 storyboard, evidence checklist, and a reminder to check the named event's own rules.
- Made `scripts.seed` an idempotent, transactional Emberfall judge seed. It creates three `[SIM]` heroes, one consented simulated viewer moment, a canonical world flag, and two prior Chronicle records. It prints the Chronicle URLs and creates no OAuth tokens. Fixed a missing commit boundary discovered by checking fresh-database counts.
- Added a one-action **Start judge demo** entry point, explicit `[SIM]`/no-Twitch labels, frontend error boundaries, and two Zod simulator-contract tests. Added version/build fields to `/healthz` and `/readyz` (`BUILD_VERSION`, default `local`).
- Added `.gitignore`/`.dockerignore` coverage for database variants, recordings/videos, token files and certificate bundles. Generated `frontend/package-lock.json` and changed the frontend Dockerfile to use `npm ci`. Updated repository commands to invoke pytest as `python -m pytest`.
- Scoped the React effect lint suppression only to dashboard/simulator/overlay screens whose effects intentionally initiate async refreshes or initialize URL state. Three unrelated hook/style warnings remain.
- Rewrote stale architecture status and corrected entity descriptions. Updated Twitch/OBS docs to match loopback PostgreSQL port 5433 and the judge path. No production profile or deployment was added; hosting was out of scope and no deployment was made.

### Verification commands and results

- `docker compose -p mythoslive-stage9fresh --env-file <temporary isolated env> -f docker-compose.yml -f <temporary ports override> up -d db` — **passed**; started a new PostgreSQL/pgvector container and new project-scoped volume on port 15433. The actual generated key remained in an ignored temporary file and was not printed.
- `docker compose ... run --rm --no-deps backend alembic upgrade head` — **passed** on the empty database through `0006_streamer_control_room`.
- `docker compose ... run --rm --no-deps backend python -m scripts.seed` — **passed twice**; printed two local Chronicle URLs. Post-seed SQL counts: 3 sample heroes, 1 sample memory, 2 sample Chronicles, 0 OAuth tokens. The later complete simulator added 15 additional simulator viewers/heroes.
- `docker compose ... run --rm --no-deps backend python -m scripts.sim` — **passed**; 15 personas, state `ENDED`, 209 engine events, seed 2026.
- `docker compose ... run --rm --no-deps backend python -m pytest -q -p no:cacheprovider` — **58 passed, 1 Alembic deprecation warning** against the isolated migrated/seeded PostgreSQL database.
- `docker compose ... run --rm --no-deps backend ruff check app tests scripts` — **passed** after fixing one seed formatting violation.
- `docker compose exec -T frontend npm test` — **2 passed**. `npm run typecheck` — **passed**. `npm run lint` — **passed with 3 warnings and 0 errors**. `npm run build` — **passed**; all app routes compiled.
- `docker compose exec -T frontend npm install --package-lock-only --ignore-scripts --no-audit --no-fund` — **passed**, generated the lockfile. `npm ci --ignore-scripts --offline --dry-run` — **passed**. The initial clean Docker npm install reported 16 moderate dependency audit findings; no automatic upgrades were applied.
- `docker compose -p mythoslive-stage9fresh ... up -d --no-build backend` — **passed**. Fresh-service `GET /healthz` returned `{"status":"ok","version":"0.1.0","build":"local"}` and `/readyz` returned `{"status":"ready","database":"ok","version":"0.1.0","build":"local"}`.
- Original stack was restored with `docker compose up -d --no-build` using the existing database volume. `docker compose ps` showed DB/backend/frontend healthy. Health/readiness endpoints passed, and GET `/`, `/sim`, `/overlay`, `/dashboard`, `/dashboard/connect`, and `/chronicle/<seed-id>` returned HTTP 200.
- `py -3.12 -m compileall -q app tests scripts alembic` — **passed**. Fernet key-format smoke check passed using standard-library CSPRNG output; key value withheld.
- Credential-pattern scan excluded `.env`, `.env.example`, database files, and dependency/build directories. No credential-shaped API-key/token literals were found; textual matches were empty Compose placeholders, settings names, or fake test fixtures. `.env` exists and `.gitignore` contains the environment/database/recording/token rules. The `.env.example` encryption key is empty. **Tracked-file status was not inspected because repository instructions prohibit Git/version-control commands.**
- `docker compose up --build` in the fresh isolated project **did not complete**: frontend image layer extraction failed with Docker Desktop `read-only file system` under `/var/lib/desktop-containerd/...`. A retry stopped the Desktop engine temporarily; it was restarted and the original user stack recovered with its persistent volume intact. DB migration, seed, simulator, backend health, tests and the production frontend build were verified independently as listed above. Full all-three-service startup from a freshly built image remains unverified.
- Direct host `py -3.12 -m pytest` was not used because host pytest is not installed. Direct host `npm test` was blocked by sandbox `spawn EPERM`/missing host Zod install; the same frontend tests passed inside Compose.
- `make test` was not invoked because GNU Make is not installed in this PowerShell environment; its backend/frontend constituent commands were run individually and passed as recorded above.

### Verified versus simulated, and remaining limits

- **Verified locally:** fresh migrations; durable/idempotent sample seed; complete deterministic 15-persona campaign; database-backed backend suite; typed frontend tests, typecheck, lint, production build; healthy original local Compose stack and route/health HTTP smoke checks.
- **Simulated:** all seeded heroes, memory, Chronicles, and the full campaign persona traffic. Their names and event paths are marked `[SIM]`; the seed contains no OAuth tokens and the fresh database has zero OAuth rows.
- **Not verified:** real Twitch OAuth or real follow/raid effects on a channel; AI-provider responses; OBS transparency/compositing or browser-console behavior; public-origin cookies/WebSockets; benchmark-level end-to-end performance; all-three-service fresh `up --build` due the Docker extraction failure.
- Frontend lint still reports missing hook dependency warnings in the dashboard/overlay and an existing no-unused-expression warning in Phaser. npm's 16 moderate audit findings need a separate dependency review. No named hackathon rules URL was provided, so event-specific submission and retention requirements remain unverified.
- No deployment was made; no deployment URL exists. The running local services are not a public judge endpoint.
# Production deployment preparation (2026-11-03)

- Audited the application/process topology, port bindings, environment settings, frontend API URL usage, persistence, auth cookie/CORS behavior, and current reverse-proxy needs before adding deployment files.
- Added `backend/Dockerfile.production`, `deploy/compose.production.yml`, an Nginx WebSocket location example, Netlify build settings, root and frontend production environment examples, and `docs/production-deployment.md` with deployment, migration, verification, rollback commands and a readiness checklist.
- Production Compose exposes only an operator-selected loopback API port. PostgreSQL and Redis have no published ports, persistent named volumes, health checks, restart policies and bounded JSON logs. Redis is included as a private service but current application code does not use it. There is intentionally no separate worker service: the current engine/EventSub/AI/outbox loops start inside the API lifespan and depend on process-local coordination.
- Replaced hardcoded frontend API URL usage with `NEXT_PUBLIC_API_URL`; production builds fail clearly when it is missing. Documented Netlify App Router/Phaser compatibility as expected, but unverified by an actual Netlify deployment. Documented same-site custom domains for secure cookie behavior and WSS proxy requirements.
- No VM, Netlify site, DNS, TLS, firewall, Twitch application, or external service was changed. No deployment was performed.

### Checks performed

- `docker compose -p mythoslive-prod-check --env-file .env.production.example -f deploy/compose.production.yml config --quiet` — **passed** (Compose configuration parsing only; no services started).
- `docker compose exec -T frontend npm run typecheck` and `npm run build` — **not run**; Docker Desktop API denied access to the Docker named pipe.
- `docker build -f backend/Dockerfile.production -t mythoslive-backend:production-check .` — **not run**; Docker Buildx lock access was denied.
- `npm run typecheck` from `frontend/` — **not run**; local `node_modules`/TypeScript compiler unavailable (`tsc` not recognized).
- Fresh runtime deployment, migrations on a production-shaped DB, HTTPS/WSS, OAuth, backup/restore, and rollback — **not run**. Therefore no production readiness claim is made.

### Known deployment blockers

- Redis is not consumed by the app; event/session history, OAuth state and background work remain process-local. Keep one API replica and do not split workers until shared coordination is implemented.
- Production container build and frontend build/typecheck could not be verified in this session because Docker/local dependencies were inaccessible.
- Netlify, public domains/TLS, existing VM ports/proxy coexistence, actual Twitch redirect registration, and browser cookie/CORS/WSS behavior require operator setup and live validation.
- There is no automated schema/data rollback; take and verify a PostgreSQL backup before migrations.

### GCP VM port binding follow-up (2026-11-03)

- Set the production Compose mapping to `127.0.0.1:${API_HOST_PORT:-8001}:8000`; the production environment example defaults to host port 8001. This leaves the container listener at 8000 and avoids the user's occupied host port 8000.
- Added `deploy/check-production-ports.sh`, a read-only preflight that exits before Compose startup if the selected API port is already listening. `--new-proxy` additionally checks 80 and 443 before introducing a new proxy listener. The instructions say to merge into an already-owned proxy when present and never stop/change existing apps.
- Updated deployment and rollback docs to use the loopback API endpoint on port 8001 by default, HTTPS/WSS proxying, and a fresh listener check before binding a new public proxy.
- `docker compose -p mythoslive-prod-check --env-file .env.production.example -f deploy/compose.production.yml config --format json` — **passed**; resolved mapping was `127.0.0.1:8001 -> 8000`, and PostgreSQL/Redis had no published ports. `config --quiet` also passed.
- `bash -n deploy/check-production-ports.sh` — **not run**; Windows denied launching its WSL Bash instance (`E_ACCESSDENIED`). The script is intended to run on the Ubuntu VM and was not used to inspect the host.
- No VM checks or deployment commands were run. Current reported port availability (8001, 80, 443) is supplied by the user and must be rechecked immediately before actual deployment.

