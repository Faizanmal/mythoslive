"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { simStatusSchema } from "@/lib/simulator-contract.mjs";
type SimState = import("zod").infer<typeof simStatusSchema>;

export default function SimulatorPage() {
  const [state, setState] = useState<SimState | null>(null);
  const [name, setName] = useState("Test Viewer");
  const [message, setMessage] = useState("!join");
  const [error, setError] = useState("");
  const load = useCallback(async () => { try { setState(await apiFetch("/api/sim/status", simStatusSchema)); setError(""); } catch (e) { setError(e instanceof Error ? e.message : "Simulator API unavailable."); } }, []);
  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 2000); return () => window.clearInterval(timer); }, [load]);
  async function action(path: string, body?: object) { try { setState(await apiFetch(path, simStatusSchema, { method: "POST", headers: { "Content-Type": "application/json" }, ...(body ? { body: JSON.stringify(body) } : {}) })); setError(""); } catch (e) { setError(e instanceof Error ? e.message : "Simulator action failed."); } }
  return <main className="mx-auto min-h-screen max-w-4xl space-y-6 p-8">
    <div><p className="text-xs font-bold uppercase tracking-[.25em] text-amber-300">SIMULATION · NO TWITCH OUTPUT</p><h1 className="mt-2 text-3xl font-semibold">Chat simulator</h1><p className="mt-2 text-slate-400">A sample Emberfall campaign with simulated participants and native event fixtures. Simulator events cannot enter the Twitch send queue.</p></div>
    {error && <p role="alert" className="rounded bg-red-950 p-3 text-red-200">{error}</p>}
    <section className="rounded-xl border border-slate-700 bg-slate-900 p-5"><p>Simulation: <strong>{state?.running ? "Running" : "Stopped"}</strong> · Events: {state?.generated_events ?? 0}</p><p className="mt-2 text-sm text-emerald-200">Judge demo · [SIM] participants · no Twitch output</p><div className="mt-4 flex gap-3"><button onClick={() => void action("/api/sim/start")} className="rounded bg-emerald-600 px-4 py-2">Start Emberfall demo</button><button onClick={() => void action("/api/sim/stop")} className="rounded border border-slate-600 px-4 py-2">Stop</button></div></section>
    <section className="rounded-xl border border-slate-700 bg-slate-900 p-5"><h2 className="text-xl font-semibold">Fake chat input</h2><form className="mt-4 flex flex-col gap-3 sm:flex-row" onSubmit={e => { e.preventDefault(); void action("/api/sim/chat", { persona_name: name, message }); }}><input aria-label="Simulated viewer name" value={name} onChange={e => setName(e.target.value)} maxLength={64} className="rounded bg-slate-800 p-3"/><input aria-label="Fake chat message" value={message} onChange={e => setMessage(e.target.value)} maxLength={500} className="min-w-0 flex-1 rounded bg-slate-800 p-3"/><button className="rounded bg-violet-500 px-4 py-2">Send as simulated</button></form></section>
    <section className="rounded-xl border border-slate-700 bg-slate-900 p-5"><h2 className="text-xl font-semibold">Twitch event preview</h2><p className="mt-1 text-sm text-slate-400">Exercise follow and raid effects through the same engine event path.</p><div className="mt-4 flex flex-wrap gap-3"><button onClick={() => void action("/api/sim/social", { event_type: "channel.follow", name })} className="rounded border border-amber-700 px-4 py-2">Preview simulated follow</button><button onClick={() => void action("/api/sim/social", { event_type: "channel.raid", name, viewers: 50 })} className="rounded border border-violet-700 px-4 py-2">Preview simulated raid (50)</button></div></section>
    <section className="space-y-3"><h2 className="text-xl font-semibold">Normalized ingress</h2>{[...(state?.events ?? [])].reverse().map(event => <article key={event.event_id} className="rounded-lg border border-slate-800 bg-slate-900 p-4"><p className="text-xs text-slate-500">[SIM] {event.occurred_at}</p><p><strong>{event.actor?.display_name ?? "[SIM] system"}</strong> · {event.event_type}</p><pre className="mt-2 whitespace-pre-wrap text-sm text-slate-400">{JSON.stringify(event.payload, null, 2)}</pre></article>)}</section>
  </main>;
}
