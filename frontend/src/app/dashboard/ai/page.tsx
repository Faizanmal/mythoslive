"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { z } from "zod";
import { apiFetch } from "@/lib/api";

const statusSchema = z.object({
  enabled: z.boolean(), director_model: z.string().nullable(), fast_model: z.string().nullable(),
  embedding_model: z.string().nullable(), embedding_dimension: z.number().nullable(), embedding_status: z.enum(["disabled", "provider_unavailable", "dimension_required", "ready"]), moderation_model: z.string().nullable(),
  circuit: z.string(), requests: z.number(), failures: z.number(), latency_ms_average: z.number(),
  fallbacks: z.record(z.string(), z.number()), rejected_tools: z.number(), moderation_rejections: z.number(),
  dropped_triggers: z.number(), session_token_budget: z.number(), session_cost_budget_usd: z.number(), estimated_cost_usd: z.number(), tone: z.enum(["heroic", "grimdark", "comedic"]),
  family_friendly: z.boolean(), banned_topics: z.array(z.string()), approval_mode: z.enum(["required", "auto_safe"]),
  quill: z.object({ running: z.boolean(), pending: z.number(), sent: z.number(), dropped: z.number(), suppressed: z.number() }).optional(),
});
const pendingSchema = z.array(z.object({ id: z.string(), world_id: z.string(), payload: z.record(z.string(), z.unknown()), created_at: z.string() }));
type Status = z.infer<typeof statusSchema>;

export default function AIDashboardPage() {
  const [status, setStatus] = useState<Status | null>(null);
  const [pending, setPending] = useState<z.infer<typeof pendingSchema>>([]);
  const [bannedTopics, setBannedTopics] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const [nextStatus, nextPending] = await Promise.all([
        apiFetch("/api/ai/status", statusSchema),
        apiFetch("/api/ai/pending", pendingSchema),
      ]);
      setStatus(nextStatus);
      setBannedTopics(nextStatus.banned_topics.join(", "));
      setPending(nextPending);
      setError("");
    } catch (e) { setError(e instanceof Error ? e.message : "AI dashboard unavailable."); }
  }, []);
  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 5000); return () => window.clearInterval(timer); }, [load]);

  async function update(body: Record<string, unknown>) {
    try {
      const next = await apiFetch("/api/ai/settings", statusSchema, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      setStatus(next); setBannedTopics(next.banned_topics.join(", ")); setError("");
    } catch (e) { setError(e instanceof Error ? e.message : "Settings update failed."); }
  }
  async function review(id: string, decision: "approve" | "reject") {
    try { await apiFetch(`/api/ai/pending/${id}/${decision}`, z.record(z.string(), z.boolean()), { method: "POST" }); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : "Review failed."); }
  }

  return <main className="mx-auto min-h-screen max-w-5xl space-y-6 p-8">
    <div><Link href="/dashboard" className="text-sm text-amber-300">← Dashboard</Link><h1 className="mt-2 text-3xl font-semibold">AI Game Master</h1><p className="mt-2 text-slate-400">Creative scenes and narration only. The deterministic engine remains authoritative for actions, rewards, and outcomes.</p></div>
    {error && <p role="alert" className="rounded bg-red-950 p-3 text-red-200">{error}</p>}
    <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {[["Provider", status?.enabled ? "Configured" : "Fallback mode"], ["Circuit", status?.circuit ?? "—"], ["Average latency", `${status?.latency_ms_average ?? 0} ms`], ["Tokens", `${status?.session_token_budget ?? 0} / session`], ["Requests", status?.requests ?? 0], ["Failures", status?.failures ?? 0], ["Tool rejections", status?.rejected_tools ?? 0], ["Moderation rejections", status?.moderation_rejections ?? 0]].map(([label, value]) => <div className="rounded-lg border border-slate-700 bg-slate-900 p-4" key={String(label)}><p className="text-xs uppercase tracking-wide text-slate-500">{label}</p><p className="mt-1 font-semibold">{value}</p></div>)}
      <p className="text-sm text-slate-400 sm:col-span-2">Estimated cost: ${(status?.estimated_cost_usd ?? 0).toFixed(4)} · Per-session cap: ${status?.session_cost_budget_usd ?? 0}. Configure provider pricing in environment settings for accurate estimates.</p>
      {status?.quill && <p className="text-sm text-slate-400 sm:col-span-2">Quill {status.quill.running ? "running" : "stopped"} · {status.quill.pending} queued · {status.quill.sent} sent · {status.quill.suppressed} suppressed</p>}
    </section>
    <section className="rounded-xl border border-slate-700 bg-slate-900 p-5"><h2 className="text-xl font-semibold">Creative and safety settings</h2><div className="mt-4 grid gap-4 sm:grid-cols-2">
      <label className="grid gap-2 text-sm">Tone<select className="rounded bg-slate-800 p-3" value={status?.tone ?? "heroic"} onChange={e => void update({ tone: e.target.value })}><option value="heroic">Heroic</option><option value="grimdark">Grimdark (PG-13)</option><option value="comedic">Comedic</option></select></label>
      <label className="grid gap-2 text-sm">World event approval<select className="rounded bg-slate-800 p-3" value={status?.approval_mode ?? "required"} onChange={e => void update({ approval_mode: e.target.value })}><option value="required">Require streamer approval</option><option value="auto_safe">Apply allowlisted safe events</option></select></label>
      <label className="flex items-center gap-3 text-sm"><input type="checkbox" checked={status?.family_friendly ?? true} onChange={e => void update({ family_friendly: e.target.checked })}/> Family-friendly mode</label>
      <label className="grid gap-2 text-sm sm:col-span-2">Banned topics (comma separated)<div className="flex gap-2"><input className="min-w-0 flex-1 rounded bg-slate-800 p-3" value={bannedTopics} onChange={e => setBannedTopics(e.target.value)}/><button className="rounded bg-slate-700 px-4" onClick={() => void update({ banned_topics: bannedTopics.split(",").map(item => item.trim()).filter(Boolean) })}>Save</button></div></label>
    </div><p className="mt-4 text-xs text-slate-500">Models: Director {status?.director_model ?? "—"} · Fast {status?.fast_model ?? "—"} · Moderation {status?.moderation_model ?? "local rules"} · Embeddings {status?.embedding_model ?? "—"} · {status?.embedding_status ?? "disabled"} ({status?.embedding_dimension ?? "dimension unset"})</p></section>
    <section className="rounded-xl border border-amber-800/70 bg-slate-900 p-5"><h2 className="text-xl font-semibold">World events awaiting approval</h2><p className="mt-1 text-sm text-slate-400">Pending proposals have no canonical effect until approved.</p><div className="mt-4 space-y-3">{pending.length === 0 && <p className="text-sm text-slate-500">No pending proposals.</p>}{pending.map(item => <article className="rounded border border-slate-700 bg-slate-950 p-4" key={item.id}><p className="font-medium">{String(item.payload.description ?? "World event proposal")}</p><p className="mt-1 text-xs text-slate-500">{item.created_at} · effect: {String((item.payload.effect as Record<string, unknown> | undefined)?.flag_id ?? "allowlisted")}</p><div className="mt-3 flex gap-2"><button className="rounded bg-emerald-700 px-3 py-2 text-sm" onClick={() => void review(item.id, "approve")}>Approve</button><button className="rounded border border-slate-600 px-3 py-2 text-sm" onClick={() => void review(item.id, "reject")}>Reject</button></div></article>)}</div></section>
  </main>;
}
