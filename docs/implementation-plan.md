# Implementation Plan

Each stage is a separate authorization boundary. Complete only the stage named in the next user prompt, then stop and report. Reinspect the workspace before every stage and preserve existing work. This plan describes intended sequencing; it does not authorize future implementation.

## Stage 0 — Repository guidance and architecture (current)

**Deliverables:** `AGENTS.md`, `docs/architecture.md`, `docs/implementation-plan.md`, `.env.example`, `.gitignore`, README placeholder, and `docs/codex-log.md`.

**Acceptance:** documentation captures the fixed stack, boundaries, normalized event path, entities, trust/privacy rules, staged dependencies, and initial environment inspection. No application code or service scaffolding.

## Stage 1 — Minimal project skeleton and developer workflow

**Dependencies:** Stage 0; Python 3.12 and selected Node package manager available; inspect lockfiles before selecting npm/pnpm.

**Deliverables:** minimal backend/frontend directory skeleton, configuration loading, lint/type/test conventions, local developer commands, and Compose/PostgreSQL/pgvector setup as requested. Use CLI scaffolding for routine boilerplate only after verifying tool versions and generated files.

**Acceptance:** backend imports and health check work; frontend starts and builds; database service starts; configuration fails safely on missing required values; no secrets in tracked templates. Add focused tests and execute the requested checks.

## Stage 2 — Database foundation and typed domain contracts

**Dependencies:** Stage 1.

**Deliverables:** async SQLAlchemy setup, PostgreSQL/pgvector integration, Alembic baseline, initial identity/world/session/event/snapshot/hero schema, Pydantic contracts, structured logging, and transactional repository boundary.

**Acceptance:** migrations upgrade/downgrade on a disposable database; schema constraints and typed input validation are covered; logs redact credentials; persistence transaction behavior is verified.

## Stage 3 — Deterministic engine and simulator pipeline

**Dependencies:** Stage 2.

**Deliverables:** session state machine, classes, normalized events, commands, deterministic voting/tie resolution/stat checks, combat and boss mechanics, rewards, rate/cooldown controls, and simulator ingress.

**Acceptance:** unit tests cover legal/illegal transitions, last-vote behavior, deterministic ties, class abilities/cooldowns, scaling, combo/boss phases, reward invariants, malformed input, and simulator-to-engine event parity.

## Stage 4 — Dashboard, overlay, and streamer controls

**Dependencies:** Stage 3.

**Deliverables:** Next.js dashboard, authenticated session controls, safety and proposal review surfaces, telemetry, accessible transparent Phaser overlay, and presentation-safe real-time state delivery.

**Acceptance:** frontend checks/build pass; role boundaries prevent viewer admin actions; overlay has no credentials/secrets; key flows and readable/accessibility behavior are verified.

## Stage 5 — Twitch OAuth and core EventSub/chat integration

**Dependencies:** Stages 1–4; Twitch credentials supplied by user for local testing only.

**Deliverables:** separate broadcaster/bot OAuth roles, EventSub WebSocket lifecycle and deduplication, required core subscriptions, reconnect/resubscribe behavior, normalized event mapping, Helix chat send adapter, and configuration/operational documentation.

**Acceptance:** implementation is checked against current official Twitch docs for required versions, scopes, conditions, welcome timing, reconnect handover, close codes, and rate limits; mocked tests cover lifecycle/error paths and deduplication. Live API calls occur only with configured credentials and explicit test authorization. Optional subscriptions stay feature-flagged and nonfatal.

## Stage 6 — AI Game Master and deterministic fallback

**Dependencies:** Stages 2–4; user-configured compatible endpoint/model for any live call.

**Deliverables:** provider-neutral client, bounded prompts/context, typed outputs, allowlisted validated tools/proposals, timeout/retry policy, content deck/template fallback, and injection-resistant chat fencing.

**Acceptance:** mock tests cover unavailable/malformed/unsafe model outputs, tool validation, fallback continuation, and deterministic rule ownership. No external call without credentials and explicit authorization.

## Stage 7 — Chronicle, consent-aware memory, and opt-out

**Dependencies:** Stages 2–6.

**Deliverables:** session summaries, world-state carryover, minimized memory summaries, retention controls, and viewer deletion/anonymization flow for hero and memory records.

**Acceptance:** opt-out affects all applicable records and future processing; retention and deletion tests cover linked data; summaries exclude raw chat and sensitive content by policy.

## Stage 8 — Hardening and release readiness

**Dependencies:** Stages 1–7.

**Deliverables:** end-to-end resilience, load/rate controls, recovery/observability, accessibility and safety review, deployment documentation, and final operational runbook.

**Acceptance:** agreed test suite and build checks pass; restart/recovery and failure fallbacks are demonstrated; no secrets leak; deployment and streamer safety procedures are documented.

## Dependency outline

```text
Stage 0 -> Stage 1 -> Stage 2 -> Stage 3 -> Stage 4 -> Stage 5
                              ├───────────────┘          └-> Stage 6
                              └────────────────────────────-> Stage 7
Stages 1–7 -> Stage 8
```

The exact overlap of Twitch and AI integration can be adjusted in a later stage prompt without changing the rule that the deterministic engine owns game state.
