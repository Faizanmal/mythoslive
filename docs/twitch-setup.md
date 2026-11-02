# Twitch local setup

1. Create an application in the Twitch Developer Console. Register these exact redirect URIs (including path and port):
   - `http://localhost:8000/api/twitch/oauth/broadcaster/callback`
   - `http://localhost:8000/api/twitch/oauth/bot/callback`
2. Copy `.env.example` to `.env`, fill `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET`, and set both role redirect URI variables to the exact registered values. Generate a Fernet key locally with:

   ```powershell
   py -3.12 -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
   ```

   Put the generated value in `ENCRYPTION_KEY`. Never commit `.env` or paste its secrets into the browser.
3. Start the stack with `docker compose up --build`. PostgreSQL health gates backend startup; the backend runs Alembic before Uvicorn; frontend starts after backend health. API is port 8000, UI is port 3000, PostgreSQL is bound to loopback port 5433 (internal Compose port 5432).
4. Open `http://localhost:3000/dashboard/connect`. Connect broadcaster first and approve `channel:bot` plus `moderator:read:followers`. Then connect the bot user and approve `user:read:chat`, `user:write:chat`, and `user:bot`. Use separate Twitch identities when desired. The bot must be authorized for the channel by `channel:bot` or be a moderator.
5. Wait for the dashboard to show EventSub connection and subscription state. `channel.follow` requires broadcaster authorization with `moderator:read:followers`; chat uses the bot authorization. Permission failures are visible as degraded/failed status with remediation.
6. Bot sending remains disabled. Explicitly enable it in the dashboard before using the test-message button; inspect the displayed sent/dropped result and queue metrics. Disable it after the test if appropriate.
7. Add the displayed `/overlay` URL to OBS as a Browser Source (1920x1080). The page background is transparent.

The `/sim` route works without Twitch credentials. Its persona and fake-chat events are labeled `[SIM]` and cannot be submitted to the Twitch outbox.

Simulator login is intentionally available only when `ENVIRONMENT=development` and the request uses localhost. Do not expose that local-only mode on a public deployment. The secure dashboard cookies require HTTPS in public deployments; register public OAuth callback URLs exactly and set the browser origin in `CORS_ORIGINS`.

To disconnect a role, use its dashboard button. The backend asks Twitch to revoke its access token and removes the encrypted local token record. If a scope was declined, disconnect and reconnect to approve it. Never share OAuth codes, access/refresh tokens, client secrets or Fernet keys.

Current endpoint, scope, version, reconnect and rate-limit references are recorded in [twitch-implementation-notes.md](twitch-implementation-notes.md).
