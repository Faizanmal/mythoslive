# Submission support (draft; not submitted)

## Devpost project description

**MythosLive turns a live Twitch chat into a cooperative fantasy campaign.** Viewers join persistent heroes, vote on the party's choices, and fight through a deterministic Emberfall adventure shown in a transparent OBS overlay. A streamer dashboard provides session controls, safety settings, an approval queue for consequential story proposals, and a live event view. Optional AI adds bounded narrative flavor; deterministic rules own every vote, stat check, reward, and combat outcome, so the campaign can continue when AI is unavailable.

The local judge mode runs without Twitch or AI credentials and labels its participants and events as simulated. The application includes Twitch OAuth and EventSub/Helix integration paths, but this description does not claim a real channel was exercised as part of this release verification. Follow and raid game effects are implemented; optional subscriptions, cheers, Channel Points rewards, and native polls are not enabled.

## Demo storyboard — target 2:45–2:58

| Time | Shot and narration | Evidence / caveat |
| --- | --- | --- |
| 0:00–0:15 | Landing page: explain “chat becomes the party” and show the Emberfall simulator CTA. | State clearly that the visible sample card is illustrative. |
| 0:15–0:40 | Start the local judge path; show `[SIM]` labels and the seeded heroes/Chronicle history. | This segment is simulated. |
| 0:40–1:10 | Show a real test-channel chat command and vote reflected in the overlay. | Record only after the owner connects a Twitch test channel; otherwise omit/label the segment simulated. |
| 1:10–1:35 | Show vote changes, deterministic encounter/boss interaction, and the transparent OBS overlay. | Use an actual OBS Browser Source capture if available; browser preview alone is not OBS verification. |
| 1:35–2:00 | In the dashboard, inspect a pending story proposal, approve one and veto another, then demonstrate Panic Pause and explicit Resume. | Use the simulator for local repeatability; identify it on screen. |
| 2:00–2:25 | End a session, open its Chronicle, then show the next-session “Previously on” and a consented, real stored-memory callback. | Use seeded/history data only where it accurately matches; do not imply a simulated memory came from a live viewer. |
| 2:25–2:48 | Show deterministic fallback with AI unavailable and briefly show architecture/Codex development evidence. | Do not show secrets, `.env`, tokens, or private prompts. |

## Screenshot / capture checklist

- [ ] Real Twitch chat command/vote and its corresponding event (only after authorized test-channel verification).
- [ ] Overlay with live vote cards and readable party UI.
- [ ] Boss encounter/phase UI.
- [ ] Dashboard approval queue with approve/veto outcome.
- [ ] Public Chronicle recap with no transcript or secrets.
- [ ] Clearly labelled simulator/judge mode.
- [ ] Codex thread showing development work; redact local paths or personal details if needed.
- [ ] Optional OBS Browser Source capture demonstrating transparency.
- [ ] Demo video between 2:45 and 2:58, if required by the event.

## Event rule reminder

No specific hackathon event page or rules URL was provided, so event-specific deadlines, judging access, video requirements, and availability-period rules have not been verified. Devpost's official guidance says each event defines its own submission requirements and may specify video/access requirements ([Creating Hackathon Rules](https://help.devpost.com/article/140-creating-hackathon-rules)); check the named event's rules before submission. Keep the repository, running demo, and video available for the period its rules require. Do not submit automatically.
