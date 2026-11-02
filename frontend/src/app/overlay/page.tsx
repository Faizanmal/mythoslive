"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { z } from "zod";
import { PhaserStage, type OverlayState } from "@/components/overlay/phaser-stage";
import type { KenneyManifest } from "@/components/overlay/phaser-stage";
import { useOverlayRealtime } from "@/components/overlay/realtime-client";

function text(value: unknown, fallback = "") { return typeof value === "string" ? value : fallback; }
function record(value: unknown): Record<string, unknown> { return value && typeof value === "object" ? value as Record<string, unknown> : {}; }
function list(value: unknown): Record<string, unknown>[] { return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => !!item && typeof item === "object") : []; }
const manifestSchema = z.object({
  tileSheet: z.string().startsWith("/assets/kenney/").optional(),
  tileFrameWidth: z.number().int().positive().optional(), tileFrameHeight: z.number().int().positive().optional(), floorFrame: z.number().int().nonnegative().optional(),
  heroSheet: z.string().startsWith("/assets/kenney/").optional(),
  heroFrameWidth: z.number().int().positive().optional(), heroFrameHeight: z.number().int().positive().optional(), heroFrame: z.number().int().nonnegative().optional(),
}).strict().superRefine((manifest, context) => {
  if (manifest.tileSheet && (!manifest.tileFrameWidth || !manifest.tileFrameHeight)) context.addIssue({ code: "custom", message: "Tile sheet frame dimensions are required." });
  if (manifest.heroSheet && (!manifest.heroFrameWidth || !manifest.heroFrameHeight)) context.addIssue({ code: "custom", message: "Hero sheet frame dimensions are required." });
});

function Typewriter({ value }: { value: string }) {
  const [shown, setShown] = useState("");
  useEffect(() => {
    setShown("");
    if (!value) return;
    let index = 0;
    const timer = window.setInterval(() => {
      index += 2;
      setShown(value.slice(0, index));
      if (index >= value.length) window.clearInterval(timer);
    }, 24);
    return () => window.clearInterval(timer);
  }, [value]);
  return <span>{shown}<span className="type-caret">▍</span></span>;
}

function EventToast({ event }: { event: ReturnType<typeof useOverlayRealtime>["events"][number] | undefined }) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!event) { setVisible(false); return; }
    setVisible(true);
    const timer = window.setTimeout(() => setVisible(false), 4200);
    return () => window.clearTimeout(timer);
  }, [event?.event_id]);
  if (!event || !visible) return null;
  const leveled = event.event_type === "hero_updated" && Boolean(event.payload.level_up);
  const message = event.event_type === "hero_joined" ? `${text(event.payload.display_name, "A wayfarer")} joined the party` : event.event_type === "boss_phase" ? `${text(event.payload.boss, "The guardian")} · phase ${String(event.payload.phase)}` : leveled ? `${text(event.payload.display_name, "A hero")} reached level ${String(event.payload.level)}!` : text(event.payload.text);
  return <div className="event-toast" key={event.event_id}>{event.event_type === "hero_joined" || leveled ? "✦" : "✧"} {message}</div>;
}

function VoteCard({ scene, votes, phaseStarted }: { scene: Record<string, unknown>; votes: unknown; phaseStarted: unknown }) {
  const options = list(scene.options);
  const voteData = record(votes);
  const tally = record(voteData.tally ?? votes);
  const totalWeight = Object.values(tally).reduce<number>((sum, value) => sum + Number(value || 0), 0);
  const voterCount = Number(voteData.votes ?? totalWeight);
  const [seconds, setSeconds] = useState(10);
  useEffect(() => {
    const start = typeof phaseStarted === "string" ? new Date(phaseStarted).getTime() : Date.now();
    const update = () => setSeconds(Math.max(0, Math.ceil(10 - (Date.now() - start) / 1000)));
    update();
    const timer = window.setInterval(update, 250);
    return () => window.clearInterval(timer);
  }, [phaseStarted]);
  if (!options.length) return null;
  return <section className="overlay-panel vote-panel" aria-label="Community vote">
    <div className="panel-heading"><span>THE PARTY DECIDES</span><strong>{seconds}s</strong></div>
    <div className="vote-options">{options.slice(0, 4).map((option, index) => {
      const count = Number(tally[String(index + 1)] ?? 0);
      const percent = totalWeight ? count / totalWeight * 100 : 0;
      return <div className="vote-option" key={`${index}-${text(option.text)}`}>
        <div className="vote-option-label"><b>{index + 1}</b><span>{text(option.text, "A path ahead")}</span><small>{count}</small></div>
        <div className="vote-track"><i style={{ width: `${percent}%` }} /></div>
      </div>;
    })}</div>
    <div className="vote-footer">{voterCount} vote{voterCount === 1 ? "" : "s"} cast · !1–!{options.length}</div>
  </section>;
}

function BossPanel({ enemy, phase, events }: { enemy: Record<string, unknown>; phase: unknown; events: ReturnType<typeof useOverlayRealtime>["events"] }) {
  const hp = Math.max(0, Number(enemy.hp ?? 0));
  const maxHp = Math.max(1, Number(enemy.max_hp ?? hp ?? 1));
  const combo = [...events].reverse().find((event) => event.event_type === "combo");
  return <section className="overlay-panel boss-panel" aria-label="Boss status">
    <div className="boss-heading"><div><small>EMBERFALL THREAT</small><h2>{text(enemy.name, "Cinderbound Guardian")}</h2></div><div className="phase-markers">{[1, 2, 3].map((item) => <i className={Number(phase ?? 1) >= item ? "active" : ""} key={item} />)}</div></div>
    <div className="boss-health"><i style={{ width: `${Math.max(0, hp / maxHp * 100)}%` }} /></div>
    <div className="boss-meta"><span>{hp.toLocaleString()} / {maxHp.toLocaleString()} HP</span><strong>PHASE {String(phase ?? 1)}</strong></div>
    <p className="mechanic-callout">⚠ {text(enemy.mechanic, "The foe watches the party…").replaceAll("_", " ").toUpperCase()}</p>
    {combo && <div className="combo-meter"><span>PARTY COMBO</span><b>{String(combo.payload.participants ?? 3)} adventurers · +{String(combo.payload.bonus_damage ?? 0)} damage</b></div>}
  </section>;
}

export default function OverlayPage() {
  const [key, setKey] = useState("");
  const [layout, setLayout] = useState<"bottom" | "right" | "full">("bottom");
  const [debug, setDebug] = useState(false);
  const [fps, setFps] = useState(30);
  const [assetsReady, setAssetsReady] = useState(false);
  const [assetsChecked, setAssetsChecked] = useState(false);
  const [assetManifest, setAssetManifest] = useState<KenneyManifest | null>(null);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setKey(params.get("key") ?? "");
    const requested = params.get("layout");
    if (requested === "right" || requested === "full" || requested === "bottom") setLayout(requested);
    setDebug(params.get("debug") === "1");
    document.documentElement.classList.add("overlay-transparent");
    // Kenney assets are optional. The engine remains fully usable with local vector art.
    void fetch("/assets/kenney/asset-manifest.json", { cache: "no-store" })
      .then((response) => response.ok ? response.json() : null)
      .then(async (manifest) => {
        const parsed = manifestSchema.safeParse(manifest);
        if (parsed.success) {
          const [tileOk, heroOk] = await Promise.all([
            parsed.data.tileSheet ? fetch(parsed.data.tileSheet, { method: "HEAD" }).then((r) => r.ok).catch(() => false) : Promise.resolve(true),
            parsed.data.heroSheet ? fetch(parsed.data.heroSheet, { method: "HEAD" }).then((r) => r.ok).catch(() => false) : Promise.resolve(true),
          ]);
          setAssetManifest({ ...parsed.data, ...(!tileOk ? { tileSheet: undefined } : {}), ...(!heroOk ? { heroSheet: undefined } : {}) });
          setAssetsReady(Boolean((parsed.data.tileSheet || parsed.data.heroSheet) && tileOk && heroOk));
        } else setAssetsReady(false);
        setAssetsChecked(true);
      })
      .catch(() => { setAssetsReady(false); setAssetsChecked(true); });
    return () => document.documentElement.classList.remove("overlay-transparent");
  }, []);
  const realtime = useOverlayRealtime(key);
  const state = realtime.state as OverlayState | null;
  const scene = record(state?.scene);
  const enemy = record(state?.enemy);
  const recap = record(state?.recap);
  const heroes = list(state?.heroes).slice(0, 40);
  const extraHeroes = Math.max(0, list(state?.heroes).length - 40);
  const narration = useMemo(() => {
    for (const event of [...realtime.events].reverse()) {
      if (event.event_type === "narration") return text(event.payload.text);
    }
    return text(state?.narration, "Welcome, wayfarers, to Emberfall.");
  }, [realtime.events, state?.narration]);
  const toast = [...realtime.events].reverse().find((event) => event.event_type === "toast" || event.event_type === "hero_joined" || event.event_type === "boss_phase" || (event.event_type === "hero_updated" && Boolean(event.payload.level_up)));
  const onDiagnostics = useCallback((value: number) => setFps(value), []);
  const stateName = text(state?.state, "LOBBY");
  const commands = stateName === "VOTE" ? `!1–!${Math.max(2, list(scene.options).length)}  !vote <1–${Math.max(2, list(scene.options).length)}>` : stateName === "COMBAT" || stateName === "BOSS" ? "!attack  !heal  !shield  !special  !hero" : stateName === "PUZZLE" ? "!answer <your guess>  !hero" : stateName === "LOBBY" || stateName === "INTRO" ? "!join  !class <warrior|mage|rogue|cleric|bard>  !hero" : stateName === "EVENT" ? "!lore  !hero" : stateName === "PAUSED" ? "Waiting for the keeper to resume" : "The next chronicle awaits";
  const connected = realtime.connected;

  return <main className={`overlay-root layout-${layout}`}>
    <div className="overlay-frame">
      <PhaserStage state={state} latestEvent={realtime.latestEvent} layout={layout} assetManifest={assetManifest} onDiagnostics={onDiagnostics} />
      <div className="overlay-layer">
        {!key ? <div className="overlay-key-missing"><strong>Overlay access key required</strong><span>Generate a scoped key from Dashboard → Twitch connection, then use its copyable Browser Source URL.</span></div> : null}
        {key && !connected && <div className="overlay-connection">{realtime.error || "Reconnecting to Emberfall…"}</div>}
        {assetsChecked && !assetsReady && process.env.NODE_ENV === "development" && <div className="asset-warning">DEV · Kenney Tiny Dungeon / Tiny Town packs not found. Showing original vector placeholders.</div>}
        <div className="world-topline"><span className="world-sigil">✦</span><span>EMBERFALL</span><i /> <strong>{stateName}</strong><small>{String(state?.torches_lit ?? 0)}/12 TORCHES · MORALE +{String(state?.morale_bonus ?? 0)}{list(state?.reinforcements).length ? ` · ${list(state?.reinforcements).length} REINFORCEMENT SQUAD${list(state?.reinforcements).length === 1 ? "" : "S"}` : ""}</small></div>
        {stateName === "PAUSED" && <div className="panic-pause" role="status"><div><span>MYTHOSLIVE · STREAM PAUSED</span><strong>The chronicle is safely held.</strong><small>The keeper must resume the session to continue.</small></div></div>}

        <div className="overlay-left-rail">
          {stateName === "VOTE" && <VoteCard scene={scene} votes={state?.votes} phaseStarted={state?.phase_started_at} />}
          {stateName === "BOSS" && <BossPanel enemy={enemy} phase={state?.boss_phase} events={realtime.events} />}
          {stateName === "PUZZLE" && <section className="overlay-panel puzzle-panel"><small>THE RIDDLE KEEPER</small><p>{text(record(state?.puzzle_update).question, text(record(scene.riddle).question, "A puzzle is being prepared…"))}</p><span>{record(state?.puzzle_update).solved ? "SOLVED · !answer" : "Answer in chat with !answer"}</span></section>}
          {stateName === "RECAP" || stateName === "ENDED" ? <section className="chronicle-card"><div className="chronicle-seal">✦</div><small>CHRONICLE OF EMBERFALL</small><h2>{text(recap.title, "The Emberfall Chronicle")}</h2><p className="party-total">{String(recap.party_size ?? heroes.length)} adventurers · a tale worth retelling</p><div className="chronicle-moments">{(Array.isArray(recap.key_moments) ? recap.key_moments : []).slice(-4).map((moment, index) => <p key={`${index}-${String(moment)}`}>✧ {String(moment)}</p>)}</div><div className="chronicle-rewards"><b>HALL OF HEROES</b>{Object.entries(record(recap.mvp_categories)).map(([category, name]) => name ? <span key={category}>{category}: {String(name)}</span> : null)}{(Array.isArray(recap.level_ups) ? recap.level_ups : []).map((item, index) => <span key={`level-${index}`}>Level up · {String(item)}</span>)}<span>Cosmetic gold carried by the party · {heroes.reduce((sum, hero) => sum + Number(hero.gold ?? 0), 0)} ✦</span></div><p className="cliffhanger">{text(recap.cliffhanger)}</p></section> : null}
        </div>

        <div className="narration-ribbon"><div className="quill-portrait"><span>Q</span><i>✦</i></div><div><small>QUILL · CHRONICLER</small><p><Typewriter value={narration} /></p></div></div>
        <EventToast event={toast} />

        <div className="party-rail"><div className="party-header"><span>THE PARTY</span><b>{list(state?.heroes).length}/∞</b></div><div className="party-list">{heroes.slice(0, 5).map((hero, index) => <div className="party-member" key={`${String(hero.display_name)}-${index}`}><i style={{ background: ["#b77a58", "#7e86aa", "#7eab8f", "#ae8c57", "#987eb6"][index % 5] }}>{text(hero.class_name, "?").slice(0, 1).toUpperCase()}</i><span><b>{text(hero.display_name, "Wayfarer")}</b><small>{text(hero.class_name, "wayfarer")} · Lv {String(hero.level ?? 1)}</small></span><em>{String(hero.hp ?? 0)} HP</em></div>)}</div>{extraHeroes > 0 && <p className="party-more">+{extraHeroes} more adventurers</p>}</div>

        <div className="command-ticker"><small>CHAT COMMANDS</small><span>{commands}</span></div>
        {debug && <div className="debug-hud"><b>DEBUG</b><span>{fps} FPS</span><span>{connected ? "WS LIVE" : "WS RETRY"}</span><span>SEQ {realtime.sequence}</span><span>{realtime.lastEventAt ?? "Awaiting event"}</span><span>{assetsReady ? "KENNEY MANIFEST" : "VECTOR FALLBACK"}</span></div>}
      </div>
    </div>
  </main>;
}
