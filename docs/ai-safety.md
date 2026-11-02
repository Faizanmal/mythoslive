# MythosLive AI Game Master safety

The AI Game Master is an optional creative layer. The deterministic engine owns state transitions, vote arithmetic, combat, cooldowns, numerical rewards, and session completion. The model can request only typed tools; every request is validated against local schemas and content IDs before the engine applies it.

## Configuration

Set these values in an ignored local `.env` file (see `.env.example`):

- `AI_API_BASE_URL`, `AI_API_KEY`
- `AI_DIRECTOR_MODEL`, `AI_FAST_MODEL`, `AI_EMBEDDING_MODEL`, `AI_MODERATION_MODEL`
- `AI_TIMEOUT_SECONDS`, `AI_MAX_RETRIES`, `AI_CIRCUIT_FAILURE_THRESHOLD`, `AI_CIRCUIT_RESET_SECONDS`
- `AI_SESSION_TOKEN_BUDGET`, `AI_SESSION_COST_BUDGET_USD`
- `AI_INPUT_COST_PER_MILLION`, `AI_OUTPUT_COST_PER_MILLION`
- `AI_TONE`, `AI_FAMILY_FRIENDLY`, `AI_BANNED_TOPICS`, `AI_APPROVAL_MODE`

Set cost rates to the provider's current rates to make the estimated cost budget meaningful. Rates default to zero because compatible providers and models price differently. Token usage is recorded even when costs are not estimated. A zero token budget disables provider generation; a zero cost budget disables the cost threshold.

Configure a moderation model before enabling creative generation. Generated text fails closed to the canned narrator when the moderation model is missing, rejects content, or is unavailable. With no moderation model, simulator and game sessions still run on the deterministic deck and canned lines.

## Data and prompts

- Chat is held in a bounded per-world digest. Individual viewer IDs and raw histories are not sent. Commands are aggregated; up to four short chat samples may be sent after local checks and provider moderation.
- If a moderation model is configured but unavailable or rejects a request, raw chat samples are omitted from model context. The simulator still proceeds.
- User-provided data is explicitly fenced as untrusted input. It cannot change system instructions, allowlists, or engine authority.
- Viewer names are not included in AI context. Recaps and memories are bounded and sanitized.
- Prompts, provider response bodies, API keys, and tokens are never written to logs or `llm_calls`. Telemetry stores model name, latency, status, token counts, estimated cost, and a bounded reason label.

## Tool authority and approval

- Templates, enemies, bosses, riddles, mechanics, effects, and reward tiers are enumerated locally. Arbitrary SQL, code, URLs, raw database IDs, XP/gold values, player targets, cooldown changes, or impersonation are not accepted.
- A scene request during VOTE must identify the active local scene. It may change only moderated flavor text. Vote options, timer, and outcome are unchanged.
- Reward requests use fixed engine-owned tiers and are accepted only during EVENT. The engine enforces all caps and persists the outcome.
- AI world changes are pending by default. The dashboard approval queue controls when an allowlisted flag becomes canonical. `auto_safe` applies only the hard-coded safe flags.
- Output moderation runs before narration, scene flavor, memories, and world event descriptions reach the overlay or database. Local block rules remain active if the moderation provider is unavailable.
- The existing deterministic moderator pause path does not depend on the AI service.

## Fallback behavior

The Director tries the configured primary model, then the configured fast model. Invalid credentials, malformed output, provider timeouts/rate limits, tool validation errors, circuit-open state, and exhausted token/cost budgets move generation to a Jinja-rendered canned narrator line. The deterministic Emberfall scene, boss, and riddle decks continue to drive a complete session without provider configuration.

AI requests have bounded timeouts and retries with jitter. The circuit breaker prevents repeated calls during provider outages and allows a fast-model probe. Cancellation is propagated when a newer phase supersedes an in-flight request.

## Operator controls and known limits

`/dashboard/ai` reports provider/circuit state, latency, fallback reasons, tool and moderation rejections, and estimated token/cost use. Tone, family-friendly mode, banned topics, and approval mode can be changed there; these settings are in-memory for the current backend process and revert to environment defaults after restart.

The client implements OpenAI-compatible Chat Completions, Moderations, and Embeddings endpoints. Actual model availability, moderation quality, provider-specific structured-output compatibility, and pricing require a configured provider and were not live-tested. When cost rates remain zero, cost budget telemetry is zero and only token limits constrain generation.
