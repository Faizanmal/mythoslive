# OBS Browser Source setup

The MythosLive overlay is a transparent Phaser 3 scene designed for a 16:9 Browser Source. It draws only the world and game widgets; the page outside those elements stays transparent so the streamer's gameplay and facecam remain visible.

## Start locally

1. Start PostgreSQL, backend, and frontend with `docker compose up --build` from the repository root. The database starts first, the backend waits for database health and applies Alembic migrations, then the frontend starts after backend readiness.
2. Open `/dashboard/connect` (normally `http://localhost:3000/dashboard/connect`). Click **Create overlay key**. The local setup creates a read-only key for the configured simulator world. The server stores only its SHA-256 hash and returns plaintext once.
3. Click **Copy URL** and use the adjacent mini preview to confirm that the overlay connects.
4. Open `/sim`, click **Start Emberfall demo**, then send simulated chat commands such as `!join`, `!class bard`, `!1`, `!attack`, and `!answer clock`. Every generated participant/event is labelled `[SIM]`; these fixtures cannot send to Twitch. The Phaser view and dashboard event log consume the same engine event stream.

The default Browser Source URL is `http://localhost:3000/overlay?key=…&layout=bottom`. The URL contains a revocable, world-scoped, read-only overlay key; it does not contain Twitch credentials or broadcaster secrets. Generate a new key to rotate the current key, or click **Revoke key** to disable it. Existing WebSocket clients are disconnected within about five seconds of revocation.

## Add as a Browser Source

In OBS, add **Browser Source** and set:

- **URL**: paste the dashboard's copyable overlay URL.
- **Width**: `1920`.
- **Height**: `1080`.
- Enable **Shutdown source when not visible** if you want OBS to release Phaser while the source is hidden; the page reconnects and requests an authoritative snapshot when it restarts.
- Enable **Refresh browser when scene becomes active** only if you want an explicit full reload each time the OBS scene is selected.
- Leave custom CSS empty; the app sets a transparent document and canvas background.

At 1280×720, keep the source aspect ratio at 16:9. Phaser scales its 1920×1080 design surface to fit; text and panels use responsive sizing. `?layout=bottom`, `?layout=right`, and `?layout=full` adjust the widget arrangement. Add `&debug=1` to show the diagnostics HUD with FPS, WebSocket status, sequence cursor, last event time, and asset fallback status.

## Realtime recovery and privacy

The overlay connects to `/ws/overlay?key=…` and validates versioned messages with Zod. It rejects stale sequence numbers. On each reconnect it requests `/api/overlay/snapshot?key=…` and replaces its local state before continuing with new events; it does not try to replay events missed while offline. The `layout` and `debug` query parameters are visual preferences and grant no backend access.

The key authorizes presentation snapshots and read-only events for one world. It cannot send chat, control the session, or access OAuth tokens. Treat the URL as public to anyone who can view the OBS Browser Source settings, and rotate/revoke it if shared unintentionally.

## Local artwork

No art is downloaded or bundled by the app. Place your CC0 Kenney Tiny Dungeon and Tiny Town files under `frontend/public/assets/kenney/`, then follow the `asset-manifest.json` example in that directory's README to use local tile and character sprite sheets. Invalid or missing files fall back to the original vector placeholder scene; development mode displays a warning. See [asset credits](asset-credits.md) for pack sources and license notes.

## Troubleshooting

- **Overlay says key required**: generate a key in Dashboard → Twitch connection and use its copied URL.
- **Connection keeps retrying**: verify the API is healthy at `http://localhost:8000/readyz`; ensure the key has not been revoked; then refresh the Browser Source.
- **No current state**: start a simulator session or an active game session, then refresh. A snapshot is available after the first session state exists.
- **Blank art with a development notice**: optional Kenney files are absent; game widgets and Phaser vector fallbacks still work.
- **Transparent area appears black**: verify the Browser Source is not covered by another source and remove any custom CSS that paints a background. Confirm the OBS source is 1920×1080 or 1280×720.

## Stage 8 presentation notes

Critical hits receive a brief Phaser hit-stop and restrained flash/shake; boss entry and the Chronicle card have short arrival animations. To exercise the follow torch/morale and bounded raid reinforcement effects without a Twitch account, use the explicitly simulated controls on `/sim`. The landing page's sample Emberfall scene is illustrative; the simulator produces live events. No audio assets are present in this checkout, so Stage 8 did not add sound playback or a volume control. No third-party sound files are fetched.
