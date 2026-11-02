"use client";

import { useEffect, useRef, useState } from "react";
import { z } from "zod";
import type { EngineRealtimeEvent, EngineRealtimeSnapshot } from "@/lib/contracts.generated";
import { API_BASE_URL, API_WEBSOCKET_URL } from "@/lib/runtime-config";

const eventTypes = [
  "session_transition", "hero_joined", "hero_updated", "scene_started", "vote_tally",
  "vote_result", "combat_tick", "damage", "boss_phase", "combo", "puzzle_update",
  "narration", "toast", "recap", "paused",
] as const;

const engineEventSchema: z.ZodType<EngineRealtimeEvent> = z.object({
  schema_version: z.literal(1),
  message_type: z.literal("engine.event"),
  event_type: z.enum(eventTypes),
  event_id: z.string().uuid(),
  session_id: z.string().uuid(),
  world_id: z.string().uuid(),
  occurred_at: z.string().datetime({ offset: true }),
  sequence: z.number().int().positive(),
  payload: z.record(z.string(), z.unknown()),
});

const snapshotSchema: z.ZodType<EngineRealtimeSnapshot> = z.object({
  schema_version: z.literal(1),
  message_type: z.literal("engine.snapshot"),
  session_id: z.string().uuid(),
  world_id: z.string().uuid(),
  revision: z.number().int().nonnegative(),
  sequence: z.number().int().nonnegative(),
  state: z.record(z.string(), z.unknown()),
});

const statusSchema = z.object({
  schema_version: z.literal(1), message_type: z.literal("connection.status"),
  status: z.enum(["connected", "disconnected", "degraded"]), detail: z.string().nullable(),
});
const messageSchema = z.union([engineEventSchema, snapshotSchema, statusSchema]);

export interface OverlayRealtime {
  state: Record<string, unknown> | null;
  latestEvent: EngineRealtimeEvent | null;
  events: EngineRealtimeEvent[];
  connected: boolean;
  error: string;
  lastEventAt: string | null;
  sequence: number;
}

function mergeEvent(previous: Record<string, unknown> | null, event: EngineRealtimeEvent) {
  const state = { ...(previous ?? {}) };
  const payload = event.payload;
  switch (event.event_type) {
    case "session_transition": state.state = payload.state; state.phase_started_at = event.occurred_at; break;
    case "hero_joined":
    case "hero_updated": {
      if (typeof payload.display_name === "string") {
        const heroes = Array.isArray(state.heroes) ? [...state.heroes as Record<string, unknown>[]] : [];
        const index = heroes.findIndex((hero) => hero.display_name === payload.display_name);
        const hero = { ...(index < 0 ? {} : heroes[index]), ...payload };
        if (index < 0) heroes.push(hero); else heroes[index] = hero;
        state.heroes = heroes.slice(-40);
      }
      break;
    }
    case "scene_started":
      state.scene = { ...(state.scene as Record<string, unknown> ?? {}), ...payload };
      state.state = "VOTE";
      state.phase_started_at = event.occurred_at;
      state.votes = {};
      break;
    case "vote_tally": state.votes = payload.tally; break;
    case "vote_result": state.vote_result = payload; break;
    case "combat_tick":
      state.state = "COMBAT";
      if (state.phase_started_at === undefined) state.phase_started_at = event.occurred_at;
      state.enemy = { ...(state.enemy as Record<string, unknown> ?? {}), name: payload.enemy, hp: payload.enemy_hp, max_hp: payload.enemy_max_hp };
      if (Array.isArray(payload.targets)) {
        const heroes = Array.isArray(state.heroes) ? [...state.heroes as Record<string, unknown>[]] : [];
        for (const target of payload.targets as Record<string, unknown>[]) {
          const index = heroes.findIndex((hero) => hero.display_name === target.name);
          if (index >= 0) heroes[index] = { ...heroes[index], hp: target.hp, downed: target.downed, ghost: target.downed };
        }
        state.heroes = heroes;
      }
      break;
    case "damage":
      state.enemy = { ...(state.enemy as Record<string, unknown> ?? {}), hp: payload.enemy_hp };
      break;
    case "boss_phase":
      state.state = "BOSS";
      state.phase_started_at = event.occurred_at;
      state.boss_phase = payload.phase;
      state.enemy = { ...(state.enemy as Record<string, unknown> ?? {}), name: payload.boss, hp: payload.hp, max_hp: payload.max_hp ?? payload.hp, mechanic: payload.mechanic };
      break;
    case "puzzle_update": state.puzzle_update = payload; break;
    case "narration": state.narration = payload.text; break;
    case "recap": state.recap = payload; state.state = "RECAP"; break;
    case "paused": state.state = "PAUSED"; break;
  }
  return state;
}

export function useOverlayRealtime(key: string): OverlayRealtime {
  const [result, setResult] = useState<OverlayRealtime>({
    state: null, latestEvent: null, events: [], connected: false, error: "", lastEventAt: null, sequence: 0,
  });
  const current = useRef({ revision: -1, sequence: 0 });

  useEffect(() => {
    if (!key) return;
    let disposed = false;
    let socket: WebSocket | null = null;
    let retry: number | undefined;
    let attempt = 0;
    const reconcile = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/overlay/snapshot?key=${encodeURIComponent(key)}`, { cache: "no-store" });
        if (!response.ok) throw new Error(response.status === 403 ? "Overlay key expired. Create a new one in the dashboard." : `Snapshot request failed (${response.status}).`);
        const snapshot = snapshotSchema.parse(await response.json());
        if (snapshot.revision >= current.current.revision && snapshot.sequence >= current.current.sequence) {
          current.current = { revision: snapshot.revision, sequence: snapshot.sequence };
          setResult((old) => ({ ...old, state: snapshot.state, sequence: snapshot.sequence, error: "" }));
        }
      } catch (error) {
        if (!disposed) setResult((old) => ({ ...old, error: error instanceof Error ? error.message : "Could not restore overlay state." }));
      }
    };
    const connect = () => {
      if (disposed) return;
      socket = new WebSocket(`${API_WEBSOCKET_URL}/ws/overlay?key=${encodeURIComponent(key)}`);
      socket.onopen = () => {
        attempt = 0;
        // A backend restart resets its process sequence; the coming snapshot reanchors it.
        current.current.sequence = 0;
        setResult((old) => ({ ...old, connected: true, error: "" }));
        // Every reconnect takes an authoritative snapshot; deltas may have been missed.
        void reconcile();
      };
      socket.onmessage = (message) => {
        try {
          const parsed = messageSchema.parse(JSON.parse(String(message.data)));
          if (parsed.message_type === "engine.snapshot") {
            if (parsed.revision < current.current.revision || parsed.sequence < current.current.sequence) return;
            current.current = { revision: parsed.revision, sequence: parsed.sequence };
            setResult((old) => ({ ...old, state: parsed.state, sequence: parsed.sequence, error: "" }));
          } else if (parsed.message_type === "engine.event") {
            if (parsed.sequence <= current.current.sequence) return;
            current.current.sequence = parsed.sequence;
            setResult((old) => ({
              ...old,
              state: mergeEvent(old.state, parsed),
              latestEvent: parsed,
              events: [...old.events, parsed].slice(-30),
              sequence: parsed.sequence,
              lastEventAt: parsed.occurred_at,
            }));
          } else if (parsed.message_type === "connection.status") {
            setResult((old) => ({ ...old, connected: parsed.status === "connected", error: parsed.detail ?? "" }));
          }
        } catch (error) {
          setResult((old) => ({ ...old, error: error instanceof Error ? `Invalid realtime event: ${error.message}` : "Invalid realtime event." }));
        }
      };
      socket.onerror = () => setResult((old) => ({ ...old, connected: false, error: "Realtime connection failed; reconnecting." }));
      socket.onclose = () => {
        setResult((old) => ({ ...old, connected: false }));
        if (disposed) return;
        const delay = Math.min(15_000, 500 * 2 ** Math.min(attempt++, 5)) + Math.random() * 300;
        retry = window.setTimeout(connect, delay);
      };
    };
    void reconcile();
    connect();
    return () => {
      disposed = true;
      if (retry) window.clearTimeout(retry);
      socket?.close(1000, "Overlay unmounted");
    };
  }, [key]);

  return result;
}
