# Production deployment preparation

Status: deployment artifacts prepared, **not deployed**. No VM, Netlify site, DNS, TLS, firewall, or Twitch application was modified. This guide assumes the release source has already been placed on the Ubuntu VM by your approved release process; it does not pull or alter any existing application.

## Compatibility and deployment shape

Netlify's current OpenNext adapter supports Next.js App Router, SSR, route handlers, and modern Next.js releases. MythosLive uses the App Router and imports Phaser dynamically in a browser-only effect, so its frontend/overlay are compatible in principle. Netlify serves the Next app and Phaser assets; its function runtime is not used for the MythosLive API. Production deployment was not run, so compatibility with this exact Netlify site/account remains unverified. See [Netlify's Next.js guide](https://docs.netlify.com/build/frameworks/framework-setup-guides/nextjs/overview/) and [Next.js build settings](https://docs.netlify.com/build/frameworks/overview/#next-js).

The frontend uses a browser WebSocket to the VM API, not a WebSocket server hosted by Netlify. Netlify supports Next.js through its adapter, but the persistent MythosLive WebSocket server must remain on the VM. Netlify's own support guidance distinguishes a hosted frontend/API client from an application server/database ([server and database guidance](https://answers.netlify.com/t/support-guide-can-i-run-a-web-server-http-listener-and-or-database-at-netlify/3078)).

### Repository inventory

| Component | Current implementation | Production placement / listener |
| --- | --- | --- |
| Next.js App Router + Phaser overlay | `frontend/`; npm, Node 22 image for local Compose | Netlify; no VM listener. `NEXT_PUBLIC_API_URL` is compiled into browser bundles. |
| FastAPI API | `backend/app`; Uvicorn listens on `0.0.0.0:8000` inside the container | One VM container, published only to `127.0.0.1:8001` by default for the existing reverse proxy (`API_HOST_PORT` can override it). |
| Game engine, EventSub, AI Director, Quill, chat outbox | Controlled asyncio workers started by FastAPI lifespan; state/event cursors and OAuth state are process-local | Currently run inside the single backend process. There is no independent worker entrypoint. |
| PostgreSQL/pgvector | SQLAlchemy async, Alembic migrations | Private Compose network, persistent named volume, no host port. |
| Redis | Not present in app code/configuration today | Private, persistent Redis service is included as a reserved dependency, but the application does **not** connect to it yet. |
| Reverse proxy | None in repository | Merge the sample location block into the existing Nginx TLS vhost; do not replace other sites. |

Local Compose also has host-facing frontend 3000, API 8000, and DB 5433 bindings. Production Compose omits the frontend service and keeps database/Redis unpublished. Host port 8000 belongs to the existing application and must remain untouched; MythosLive uses `127.0.0.1:8001:8000`. `API_HOST_PORT` defaults to 8001 and can be overridden after a fresh availability check. Ports 80/443 are reserved for the HTTPS reverse proxy and are never published by Compose.

### Production blockers and architectural limits

- **Redis is provisioned but unused.** In-memory engine events, OAuth state, throttles, and worker coordination are not shared through Redis. Do not claim Redis-backed queuing or horizontal scaling.
- **Do not scale backend replicas or add a second worker container.** Each process would start its own engine tick loop, EventSub connection, in-memory event sequence/history, AI/Quill workers, and outbox. Duplicate subscriptions and divergent realtime state are possible. This Compose file deliberately runs one backend instance and keeps its background tasks in that process.
- OAuth state expires on process restart because its current storage is process-local. Avoid restarting during a broadcaster/bot consent flow.
- Public TLS, DNS, GCP firewall rules, Netlify environment, Twitch callbacks, and WebSocket proxy behavior need owner-side setup and live verification.
- The example credentials are placeholders. Set real values only in a restricted VM environment file/secret manager and Netlify's environment UI.

## Production configuration files

- `backend/Dockerfile.production`: runtime-only Python dependencies, non-root user, API command does not run migrations on every start.
- `deploy/compose.production.yml`: backend, one-shot migration job, PostgreSQL/pgvector, private Redis, persistent volumes, health checks, restart policies, log rotation, and loopback-only API publication.
- `deploy/nginx/mythoslive-location.conf.example`: WebSocket-capable location snippet for the existing TLS virtual host.
- `netlify.toml`: frontend base directory, build command, publish directory, and Node 22.
- `.env.production.example`: VM-only configuration placeholders.
- `frontend/.env.production.example`: public frontend URL placeholder; configure this in Netlify rather than committing an actual `.env.production`.

The backend's `/readyz` currently checks PostgreSQL, not Redis. Redis is not a backend readiness dependency until the application integrates a Redis client.

## Netlify site settings

Connect the existing repository using your approved Netlify process. Configure:

| Setting | Value |
| --- | --- |
| Base directory | `frontend` |
| Build command | `npm run build` |
| Publish directory | `.next` |
| Node version | `22` (also in `netlify.toml`) |
| Production environment variable | `NEXT_PUBLIC_API_URL=https://api.example.com` (replace with your API hostname) |

The value is public and embedded at build time; it is not a credential. Rebuild after changing it. Configure Deploy Preview/branch environments to use a deliberate staging API or the same API; do not allow accidental previews to target production if that is not intended. The Netlify Next.js adapter is automatic; this project does not pin a legacy adapter plugin.

Use a **custom domain under the same registrable domain** for frontend and API, for example `app.example.com` and `api.example.com`. The broadcaster session cookie is Secure and SameSite=Lax. Keeping both HTTPS origins same-site allows credentialed browser requests to send that cookie while CORS remains cross-origin and restricted to the exact app origin. A default `*.netlify.app` origin and an unrelated VM domain are cross-site and may fail cookie delivery under browser third-party cookie rules.

## VM environment and port isolation

### 1. Inspect the existing VM before changing anything

Run these read-only checks over SSH. Do not stop, recreate, or prune unrelated projects:

```bash
sudo ss -ltnp
sudo docker ps --format 'table {{.Names}}\t{{.Ports}}'
sudo docker volume ls
sudo nginx -T 2>/dev/null | less
```

Run `bash deploy/check-production-ports.sh` before Compose startup. It fails if the API host port is already listening and does not stop or modify any process/container. Re-run immediately before startup to reduce the check/start race. Docker will reject an occupied bind too, but dependent services might already have started if preflight is skipped. If introducing a new proxy listener, run `bash deploy/check-production-ports.sh --new-proxy` to additionally require ports 80 and 443 to be free. If an existing proxy owns them, do not use that option; merge the API vhost into the existing proxy.

Port 8000 is occupied by another Docker app and must remain untouched. Confirm the supplied port inventory is still current immediately before deployment and verify host port 8001 remains free. Check ports 80 and 443 immediately before introducing a new proxy listener. If another service has claimed either port, do not bind a competing proxy; coordinate reuse of the existing proxy or stop and resolve the conflict. Override `API_HOST_PORT` only after a fresh availability check and updating the proxy upstream. Compose uses project name `mythoslive-prod` and does not set `container_name`, so container/network/volume names are namespaced separately from other Compose projects.

### 2. Configure secrets and origins

From the deployed source directory:

```bash
cd /opt/mythoslive
umask 077
cp .env.production.example .env.production
sudoedit .env.production
```

Set the values described below. Keep the file owned by the deployment account, mode `0600`, excluded from backups that are not encrypted, and never include it in a Netlify build. Generate a Fernet key with the backend dependency installed or with:

```bash
python3 -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'
```

Use hex-only random values for PostgreSQL and Redis passwords so the database URL needs no percent-encoding. For example, generate them with `openssl rand -hex 32`, then enter them in the protected file editor. Do not paste generated values into chat or deployment logs.

Required VM values:

- `API_HOST_PORT=8001`: verify it is free immediately before startup; override only after updating the matching proxy upstream.
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL`: URL host must be `db`, port `5432`, and password must match the PostgreSQL password.
- `CORS_ORIGINS`: JSON list containing the exact frontend origin, e.g. `["https://app.example.com"]`.
- `ENCRYPTION_KEY`: valid Fernet key; keep it stable across restarts/backups because it encrypts stored Twitch tokens and signs sessions.
- `TWITCH_BROADCASTER_REDIRECT_URI=https://api.example.com/api/twitch/oauth/broadcaster/callback` and `TWITCH_BOT_REDIRECT_URI=https://api.example.com/api/twitch/oauth/bot/callback`: register these exact values in the Twitch Developer Console and set `TWITCH_CLIENT_ID`/`TWITCH_CLIENT_SECRET` on the VM only.
- `TWITCH_EVENTSUB_URL=wss://eventsub.wss.twitch.tv/ws`: the VM needs outbound DNS/TLS/WebSocket access to Twitch; Twitch EventSub WebSocket does not require an inbound webhook port.
- `REDIS_PASSWORD`: a random private Redis password. Redis currently has no application consumer.
- Optional AI variables: leave blank for deterministic fallback; otherwise configure the provider endpoint/key/models and cost budget.

Set `BUILD_VERSION` and `MYTHOSLIVE_BACKEND_IMAGE` to immutable release labels. Avoid reusing `latest` for rollbackable releases.

### 3. Reverse proxy integration

The backend listens on `0.0.0.0:8000` inside its container and publishes only `127.0.0.1:8001` on the VM (or the explicit `API_HOST_PORT` override). In the existing Nginx TLS server block for `api.<my-domain>`, merge `deploy/nginx/mythoslive-location.conf.example`, replacing `__API_HOST_PORT__` with the selected host port. It forwards HTTP and WebSocket upgrades, including `/ws/overlay`, `/api/dashboard/ws`, and `/api/game/ws/{world_id}`. Keep existing certificates, locations, listeners, and applications intact. Bind a new proxy to 80/443 only after a fresh `ss -ltnp` check confirms those ports are free; otherwise coordinate with the existing proxy owner.

After the manual merge, validate and reload the existing Nginx configuration using your normal change procedure:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Do not publish the API on `0.0.0.0`, do not publish PostgreSQL/Redis, and do not add GCP firewall rules for the chosen API port. Public requests should reach the API through the existing HTTPS virtual host only. Existing 80/443 ownership is left untouched.

## Deploy, migrate, verify, and rollback commands

These commands target only the `mythoslive-prod` Compose project. Run from `/opt/mythoslive` after environment/proxy setup; they have **not** been run against your VM. Set `API_HOST_PORT` in `.env.production` to the same selected port before using Compose. If overriding 8001, pass that value to the preflight too, e.g. `API_HOST_PORT=9001 bash deploy/check-production-ports.sh`.

### Validate and build

```bash
cd /opt/mythoslive
bash deploy/check-production-ports.sh
docker compose -p mythoslive-prod --env-file .env.production -f deploy/compose.production.yml config --quiet
docker compose -p mythoslive-prod --env-file .env.production -f deploy/compose.production.yml build backend
```

### Back up the database before migrations

```bash
umask 077
mkdir -p backups
docker compose -p mythoslive-prod --env-file .env.production -f deploy/compose.production.yml exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "backups/mythoslive-$(date -u +%Y%m%dT%H%M%SZ).sql"
```

Store an encrypted copy off the VM using your established backup process. Confirm the dump is non-empty before continuing.

### Apply migrations and start

```bash
docker compose -p mythoslive-prod --env-file .env.production -f deploy/compose.production.yml run --rm migrate
docker compose -p mythoslive-prod --env-file .env.production -f deploy/compose.production.yml up -d
docker compose -p mythoslive-prod --env-file .env.production -f deploy/compose.production.yml ps
```

The unqualified `up -d` starts the Compose project's backend, migration dependency, PostgreSQL, and Redis without touching other projects. The explicit migration command makes schema changes visible before API startup. No `down -v`, `system prune`, or VM-wide restart is part of this procedure.

### Verify local and public endpoints

```bash
docker compose -p mythoslive-prod --env-file .env.production -f deploy/compose.production.yml logs --tail=100 db redis migrate backend
curl --fail --silent --show-error http://127.0.0.1:8001/healthz
curl --fail --silent --show-error http://127.0.0.1:8001/readyz
curl --fail --silent --show-error https://api.example.com/healthz
curl --fail --silent --show-error https://api.example.com/readyz
curl --fail --silent --show-error -I https://app.example.com/
```

Replace the example domain with the actual configured host. Then, in a browser, sign into the broadcaster dashboard, complete both Twitch OAuth roles using the registered HTTPS callback URLs, verify EventSub health, create a revocable overlay key, and load the Netlify overlay. Confirm its socket URL is `wss://api.example.com/ws/overlay?...`, dashboard WebSocket is `wss://api.example.com/api/dashboard/ws`, OAuth cookies are present only on the API origin, and no browser mixed-content/CORS errors occur. These are required live checks, not checks performed by this preparation.

### Code rollback

Change `MYTHOSLIVE_BACKEND_IMAGE` in `.env.production` to the prior immutable image tag, then run:

```bash
docker compose -p mythoslive-prod --env-file .env.production -f deploy/compose.production.yml up -d --no-build backend
```

This is safe only if the previous code supports the current schema. Alembic schema downgrade/data restore is not automated here. If a migration is backward-incompatible, stop and follow a reviewed restore plan using the pre-migration backup; do not drop/recreate the database as an improvised rollback. To stop only MythosLive while retaining volumes, use `docker compose ... stop` or `down` **without** `-v`.

## Production checklist

- [ ] Confirm the VM's current listeners, containers, Nginx vhosts, firewall rules, and volumes; preserve every existing application.
- [ ] Confirm host port 8000 remains owned by the existing app and untouched; verify 8001 is free and run the read-only port preflight. Keep DB and Redis unpublished.
- [ ] Use HTTPS custom domains under the same registrable domain for Netlify and the API.
- [ ] Configure Netlify build values and `NEXT_PUBLIC_API_URL` before building; test App Router routes and the Phaser overlay on the deployed site.
- [ ] Register exact Twitch HTTPS callbacks; configure secure VM-only OAuth credentials and outbound `wss://` to EventSub.
- [ ] Create `.env.production` with mode `0600`; generate distinct database, Redis, and Fernet secrets. Do not expose secret values in logs.
- [ ] Back up PostgreSQL and confirm backup readability before applying migrations.
- [ ] Review Compose config, build the immutable backend image, run the migration job, and verify DB/API health.
- [ ] Verify 80/443 are still free before binding a new reverse proxy, or integrate with an already-owned proxy. Merge and validate the Nginx snippet without replacing existing configuration; verify HTTPS and WSS through the public origin.
- [ ] Verify broadcaster/bot OAuth, EventSub connected state, dashboard cookie/CSRF, overlay-key rotation/revocation, and a real authorized test-channel chat flow.
- [ ] Confirm Redis is still unused by application code; do not count it as a working queue/cache.
- [ ] Keep backend at one instance until Redis-backed shared state/queue and worker ownership are implemented and tested.
- [ ] Exercise backup restore, code rollback, log rotation, VM reboot recovery, and Netlify rollback before calling the service production-ready.

## Unresolved blockers

1. Redis is not integrated, despite being provisioned by Compose.
2. No standalone worker process exists. Background work is embedded in a single FastAPI lifespan; splitting or scaling it would duplicate tasks and expose in-memory state divergence.
3. OAuth state and live realtime history are process-local. Restart-safe OAuth flow, Redis pub/sub, and multi-instance coordination are not implemented.
4. No production VM, Netlify site, DNS, TLS proxy, Twitch production app, browser WSS/CORS/OAuth flow, backup restore, or reboot test has been verified.
5. No safe automated schema rollback exists. Database restore is an operator-reviewed recovery procedure.

The current code can be prepared for a **single-instance, carefully verified pilot**, but do not call this a fully production-ready, horizontally scalable deployment until these blockers and the checklist's live checks are resolved.
