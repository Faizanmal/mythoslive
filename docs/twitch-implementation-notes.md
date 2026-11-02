# Twitch implementation notes

Checked against Twitch Developer Documentation on 2026-11-02 for Stage 8. Recheck before changing auth or transport behavior.

## OAuth and token handling

- Authorization Code user-token flow, exact registered redirect URI, URL encoded scopes, random state and code exchange: [Getting tokens with OAuth](https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/).
- Token identity/client/scopes/expiry validation: [Validating tokens](https://dev.twitch.tv/docs/authentication/validate-tokens/). Saved third-party tokens are validated at startup and hourly.
- Refresh tokens rotate and must be replaced after success: [Refreshing tokens](https://dev.twitch.tv/docs/authentication/refresh-tokens/). The service serializes refresh per role in-process and checks whether another caller already replaced the rejected access token.
- Revoke endpoint: [Revoking tokens](https://dev.twitch.tv/docs/authentication/revoke-tokens/).
- Scope definitions: [Twitch OAuth scopes](https://dev.twitch.tv/docs/authentication/scopes/).

This installed, self-hosted app uses two separate user-token consent flows. The broadcaster receives `channel:bot` and `moderator:read:followers`; the bot receives `user:read:chat`, `user:write:chat`, and `user:bot`. The bot account must be authorized for the broadcaster's channel through the broadcaster's `channel:bot` consent or moderator status. Core chat/follow/raid events do not require Affiliate or Partner status. Twitch currently says chatbot verification reviews are paused; this does not block this installed app's normal user OAuth flow.

## EventSub

- WebSocket connection lifecycle, keepalive deadlines and handover: [Handling WebSocket events](https://dev.twitch.tv/docs/eventsub/handling-websocket-events/).
- WebSocket message metadata and message-ID uniqueness: [WebSocket reference](https://dev.twitch.tv/docs/eventsub/websocket-reference/).
- Subscription event, version, conditions and scope matrix: [EventSub subscription types](https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/).
- WebSocket subscription creation and user-token requirement: [Managing EventSub subscriptions](https://dev.twitch.tv/docs/eventsub/manage-subscriptions/).
- Follow, raid, subscription, cheer, redemption and poll type versions/conditions/scopes: [EventSub subscription types](https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/).
- Poll eligibility, choice count and lifecycle: [Twitch Polls API](https://dev.twitch.tv/docs/api/polls/).
- Scope definitions: [Twitch OAuth scopes](https://dev.twitch.tv/docs/authentication/scopes/).

The manager connects to `wss://eventsub.wss.twitch.tv/ws`; the timeout from `session_welcome` is reset by keepalive or notification. It uses Twitch's supplied reconnect URL exactly, waits for the replacement welcome, then closes the old socket. A plain disconnect creates a fresh session and subscriptions. Chat is `channel.chat.message` v1 using the bot user token and `broadcaster_user_id` + `user_id` condition. Follow is `channel.follow` v2 using the broadcaster token and broadcaster as moderator. Incoming raid is `channel.raid` v1 using the broadcaster token and `to_broadcaster_user_id`. Raid has no OAuth scope requirement. Required follow/raid events remain core. Their engine effects are capped and run through the same deduplicated event path as simulator fixtures.

### Stage 8 event choices and optional feature status

- Follow v2 requires `moderator:read:followers`; both `broadcaster_user_id` and `moderator_user_id` identify the channel/moderator. A follow notification lights one of at most 12 campaign torches and adds at most 3 morale points.
- Incoming raid v1 uses `to_broadcaster_user_id`, has no event scope, and the notification only exists for raids Twitch surfaces in chat. Reinforcements use a bounded 0–10,000 reported viewer count, add at most 4 units per raid, 12 units total across at most 3 squads, and expire after 90 seconds. These are event effects, not heroes or transferable rewards.
- Subscription: `channel.subscribe` v1; resub messages: `channel.subscription.message` v1; gifts: `channel.subscription.gift` v1. These use `channel:read:subscriptions`. Not activated in Stage 8; subscription effects remain behind a future operator feature flag.
- Cheers: `channel.cheer` v1 uses `bits:read`. Not activated in Stage 8.
- Channel Points custom reward redemptions: `channel.channel_points_custom_reward_redemption.add` v1 uses `channel:read:redemptions` (or manage scope). Not activated. This app does not create rewards, so it has no reward creator Client ID or fulfillment/cancellation lifecycle to manage. If a future stage creates rewards, Twitch restricts management of a custom reward/redemptions to the Client ID that created it; deleting a reward with unfulfilled redemptions can mark them fulfilled. Do not create them under a different application ID.
- Poll event subscriptions `channel.poll.begin/progress/end` v1 require `channel:read:polls` or `channel:manage:polls`; poll API operations require `channel:manage:polls`, and only Affiliate/Partner broadcasters can create polls. Polls have 2–5 choices and only one poll can be active at a time. Poll mirror is not activated; chat voting remains the default.
- Optional types remain disabled because Stage 8 did not request additional broadcaster OAuth scopes or create Twitch poll/reward resources. Optional permission/eligibility failures must be shown as unavailable and must not stop core EventSub/gameplay. No paid currency, Bits, subscription or Channel Points balance is converted into game gold, wagers or cash-equivalent rewards.

## Helix chat

- Send endpoint, fields, response (`is_sent`, `drop_reason`) and 500-character limit: [Helix API reference](https://dev.twitch.tv/docs/api/reference/) (Send Chat Message).
- Chat sending authorization and limits: [Sending and receiving chat messages](https://dev.twitch.tv/docs/chat/send-receive-messages/) and [Twitch chat](https://dev.twitch.tv/docs/chat/).
- API rate limit headers: [Twitch API guide](https://dev.twitch.tv/docs/api/guide/).

The default sender limit is 1 message/second/channel and 20 messages/30 seconds, which is conservative for a normal non-moderator, non-VIP, non-verified bot. The internal queue accepts ordered batches (default maximum 20); Helix itself sends one chat message per request. HTTP 429 responses use `Retry-After`, then `Ratelimit-Reset`, then a conservative 30-second fallback. Explicit 429 is safe to requeue; ambiguous network errors are surfaced and never automatically retried. Sending is disabled until the dashboard explicitly enables it.

## Deliberate deviations from older planning assumptions

- Use the bot user token for `channel.chat.message`, because Twitch scopes this subscription to the user whose chat is observed; use broadcaster user-token authorization for follow and raid.
- Follow is version 2, not version 1. Raid is incoming-only (`to_broadcaster_user_id`) in this implementation.
- Reconnect handover waits for the replacement welcome and does not recreate subscriptions; fresh sessions after ordinary disconnect do recreate them.
- No broadcaster Affiliate/Partner gate is added for the core events. Permission failures mark an individual subscription failed/degraded instead of taking down backend startup.
- Stage 8 keeps paid/eligibility-gated event integrations dormant; only core follow and incoming raid effects are enabled.
- OAuth refresh/state locks are in-process. Run one backend worker for this local Stage 2 build; multi-worker deployment needs shared distributed locks/state storage.

## Limits not verified against a live account

No Twitch credentials were configured in this workspace, so OAuth consent, channel bot authorization, and real EventSub delivery were not exercised. Account-specific eligibility and granted scopes are checked at consent/validation time and are shown without exposing tokens. Twitch's verification review pause and any future policy changes must be rechecked before production rollout.
