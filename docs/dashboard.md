# Streamer control room

The authenticated control room lives at `/dashboard`; Twitch and overlay-key setup remains at `/dashboard/connect`. Dashboard pages require the signed broadcaster session. Local development can use the simulator sign-in action, which only works from localhost in `development` mode. Simulator controls are also session- and CSRF-protected and cannot operate in Twitch mode.

## Access and authorization

- Broadcaster OAuth creates a 12-hour signed `Secure`, `HttpOnly`, `SameSite=Lax` dashboard cookie after Twitch identity validation. The CSRF cookie is `Secure`, `SameSite=Strict`; dashboard mutations send its value in `X-Mythos-CSRF` and must have a configured same-origin `Origin`.
- Browser-supplied world/channel IDs are ignored or rejected. API repositories scope all reads/writes to the authenticated principal's world. Overlay keys are random, hashed at rest, revocable and read-only; they cannot authenticate dashboard routes.
- Session control, configuration changes, approval decisions/edits, viewer mute/removal, and memory deletion are recorded in `dashboard_audit`.
- Pending AI world events expire after five minutes. Expiry defaults to veto; only approved allowlisted flags update canonical world state. The overlay receives a toast after approval.
- Director notes are limited to 1,000 characters, bounded in Director context, and fenced as untrusted creative context. They cannot authorize tools or override engine rules.
- Panic Pause is available independently of AI and halts deterministic game progression/actions. The overlay is covered by a neutral pause card until an explicit Resume; both transitions enter the normalized game event stream and the audit log.

## Screens

- **Live view:** current snapshot, mini-preview, vote tally, party, normalized command-only chat, game event tail and websocket connection state. Raw chat transcripts are not retained in this view.
- **Session:** start/pause/resume/end, tone, difficulty, target duration, and vote-window controls.
- **Approvals:** edit, approve, veto, expiry countdown/default, and recent decisions.
- **Director notes:** bounded notes saved for the next Director context.
- **World codex:** canon, flags, NPCs, locations, heroes, consented memory records, memory deletion and Twitch hero mute/removal. Mute/removal applies inside MythosLive; it does not issue a Twitch ban.
- **Safety:** family-friendly mode, banned topics, approval mode, command cooldown, bot rate limit, plus explicit clarification on local mute/removal.
- **Eligibility:** optional event status and reason. Subscription/channel-points capabilities remain unavailable until their OAuth scopes and account eligibility are verified; the current endpoint does not infer Affiliate/Partner status.
- **Telemetry:** model average latency, fallback calls, token/cost budgets, ingress rate, connected dashboard websocket clients, outbox counters, EventSub keepalive/error and audit history.

## Local use

1. Start DB and services with `docker compose up --build` or `make dev`.
2. Open `http://localhost:3000/dashboard/connect` and choose **Enter simulator control room** for local-only simulator access. For a real channel, connect the broadcaster through Twitch OAuth first.
3. Use **Start** and `/sim` to generate simulated personas/chat. All simulator participants are labeled `[SIM]`; chat sending to Twitch is disabled in simulator mode.
4. Use `P` for Panic Pause and `R` for Resume. Shortcuts are disabled while focus is in a form field.
5. In the approvals tab, approve or veto pending proposals. Use `/overlay?debug=1` for diagnostics. The dashboard's in-page preview is an illustrative view of the current snapshot; OBS setup remains documented in `obs-setup.md`.

The frontend refreshes the authenticated overview and lists every five seconds and also consumes `/api/dashboard/ws`. WebSocket event payloads are Zod-validated; older sequence numbers are ignored and the server sends a fresh snapshot when the bounded event history has rolled past the cursor. A failed socket shows a reconnecting/offline status and polling continues.

## Operations and known limits

- Run migrations with `make migrate`; migration `0006_streamer_control_room` adds dashboard configuration/audit, local mute state and proposal expiry.
- Control-plane settings are persisted per world; the existing AI director/outbox runtime settings are process-local and loaded from configured defaults/current saved dashboard config during startup.
- Current deployment supports one active local Twitch broadcaster/bot pair. Global EventSub/outbox health reflects that installation.
- The `duration_minutes` choice is a target for the Director; it is not currently a hard wall-clock auto-end timer.
- Current chat throughput display is the ingress accepted-count divided by process uptime, not a rolling minute window.
- Automated browser, DB authorization and responsive-device checks need a running PostgreSQL/pgvector service and installed frontend toolchain.
