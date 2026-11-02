# Judge quickstart: local Emberfall demo

This path uses the local simulator. It requires Docker Compose and a generated `ENCRYPTION_KEY`; it does not require Twitch credentials, an AI key, network access to Twitch, or a deployed URL. Every test participant and fixture is simulated.

## From a clean checkout

```powershell
Copy-Item .env.example .env
py -3.12 -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Paste the generated key into `.env` as `ENCRYPTION_KEY=...`. Then run:

```powershell
docker compose up --build -d
docker compose run --rm backend python -m scripts.seed
```

The startup gates are database healthy → backend migration/API ready → frontend. Verify `http://localhost:8000/healthz`, `http://localhost:8000/readyz`, and `http://localhost:3000`.

## Interactive demo

1. Choose **Try the simulator** on the landing page.
2. On the local connect screen, click **Start judge demo**. It enters simulator mode, starts the persona generator, and opens `/sim` in one action. **Enter simulator control room** is available if you want to open the dashboard before starting.
4. Open `/overlay` or configure an overlay key in `/dashboard/connect` and load its copied Browser Source URL. Use `/dashboard` to inspect the event stream, live state, pause, and proposal controls.
5. The fake chat input and follow/raid fixtures generate `[SIM]` events. They do not enter the Twitch chat outbox. The simulator stop button halts the persona generator; to play an entire campaign deterministically without waiting for browser timers, use the CLI command below.

The seed produces Emberfall, three labelled sample heroes, one consented simulated memory, a world flag, and two prior Chronicle records. Seeding is idempotent and will not remove an existing campaign. Open `/chronicle/<id>` using a record shown in dashboard/world history for the public recap view.

## Full campaign in batch mode

```powershell
make migrate
make seed
make sim
```

`make sim` runs a deterministic 15-persona session and prints its final state. It exercises the same engine as Twitch and browser simulator events but does not run a Twitch connection. The command writes a new simulated session to the local database.

## Shutdown and data

```powershell
docker compose down
```

This preserves the named database volume. Avoid `docker compose down -v` if you want to keep the seed and demo history. To reset, remove only this project's volume deliberately after confirming the project name and that the local campaign data is disposable.

## What the demo does not prove

The judge path proves simulator ingress, deterministic engine behavior, local persistence, and UI wiring. It does not prove real Twitch OAuth/EventSub delivery, public-origin cookies/WebSockets, external AI output, OBS alpha compositing on a streaming machine, or 300-viewer capacity. Use owner-authorized Twitch credentials and a test channel for those checks.
