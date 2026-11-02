# MythosLive Repository Guide

## Project rules

MythosLive turns Twitch chat into a persistent fantasy party. The deterministic game engine owns game rules, numerical state, validation, and transitions. AI may generate bounded narrative content and may only invoke validated, allowlisted tools. If AI is unavailable or returns invalid output, deterministic templates keep the session running.

Follow the product, architecture, Twitch integration, game rules, trust, privacy, accessibility, and safety requirements in the project brief. In particular:

- Simulator and Twitch input enter one normalized event pipeline.
- Validate API and WebSocket inputs; apply rate limits and cooldowns.
- Keep state-changing work transactional where practical; persist snapshots and an append-only event log.
- Fence untrusted chat from instructions. Never expose credentials, overlay secrets, or admin actions.
- Minimize retained chat data. Support documented viewer opt-out deletion/anonymization.
- Keep optional Twitch features behind flags; optional permission failures must not stop core gameplay.
- Never hardcode an AI provider/model. Store only placeholder values in `.env.example`.
- Do not call Twitch or LLM services without configured credentials and explicit test authorization.
- Do not sign up for services or incur costs.
- Inspect existing files before each stage and preserve working code. Use migrations, typed schemas, structured logging, and tests as features are implemented.
- Do not run Git/version-control commands or create commits, branches, or pull requests.
- Work only on the stage explicitly requested. Stop at the end of each stage and wait for the next prompt.

## Repository conventions

- Python backend targets Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async, and PostgreSQL/pgvector.
- Frontend uses Next.js App Router, React, TypeScript, Tailwind CSS, shadcn/ui, Zustand, Zod, and Phaser 3.
- Keep domain rules independent of transport, persistence, and LLM providers.
- Use typed request/event contracts, explicit state transitions, migrations, structured logs, and focused tests.
- Keep documentation current; append meaningful stage outcomes to `docs/codex-log.md`.
- Follow the package manager already established by manifests/lockfiles. Inspect the environment and lockfiles before choosing npm or pnpm. Do not switch package managers silently.
- Use CLI scaffolding for boilerplate when a stage calls for it, after checking available tools and existing files. Do not scaffold future stages early.
- Never commit secrets or real credentials.

## Commands

Initial inspection found Python 3.12.8 (`py -3.12`), Node.js 26.5.0, npm 12.0.1, Docker CLI 29.7.2, and Docker Compose 5.5.0. The npm generator was unavailable because npm is configured offline and `create-next-app` was not cached. Docker Desktop's Linux engine must be started before Compose can run. Recheck runtimes and package lockfiles when a stage begins.

- Local stack: `docker compose up --build`; stop with `docker compose down`.
- Backend checks: `docker compose run --rm backend python -m pytest -q` and `docker compose run --rm backend ruff check app tests scripts`.
- Frontend checks: `docker compose run --rm frontend npm run typecheck`, `npm run lint`, and `npm run build`.
- Database migration: `docker compose run --rm backend alembic upgrade head`.
- Local seed/simulator placeholders: `docker compose run --rm backend python -m scripts.seed` and `python -m scripts.sim`.
- Convenience targets: `make dev`, `make down`, `make test`, `make lint`, `make typecheck`, `make migrate`, `make seed`, `make sim`.

The backend targets Python 3.12. Frontend uses npm and commits `frontend/package-lock.json`; use `npm ci` for repeatable installs.

## Directory map

```text
.
├── AGENTS.md
├── README.md
├── .env.example
├── .gitignore
├── .dockerignore
├── docker-compose.yml
├── Makefile
├── backend/
│   ├── app/              # API, configuration, contracts, persistence, repositories, services
│   ├── alembic/          # Initial migration and migration environment
│   ├── scripts/          # Type generation, local seed, simulator placeholder
│   └── tests/
├── frontend/
│   └── src/
│       ├── app/          # App Router placeholder routes
│       ├── components/   # Overlay and UI foundations
│       ├── lib/          # API client and generated event types
│       └── stores/       # Zustand state scaffolding
└── docs/
    ├── architecture.md
    ├── implementation-plan.md
    └── codex-log.md
```

The backend package owns API, settings, encryption, persistence entities/migrations, and normalized contracts. The frontend owns App Router pages, Phaser overlay, generated contract types, and UI foundations. Compose coordinates DB → backend → frontend.
