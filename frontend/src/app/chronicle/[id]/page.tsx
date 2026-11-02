"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { z } from "zod";
import { API_BASE_URL } from "@/lib/runtime-config";

const chronicleSchema = z.object({
  id: z.string(), title: z.string(), recap: z.object({}).passthrough(), created_at: z.string(),
}).passthrough();
type Chronicle = z.infer<typeof chronicleSchema>;
const list = (value: unknown) => Array.isArray(value) ? value : [];
const record = (value: unknown) => value && typeof value === "object" ? value as Record<string, unknown> : {};

export default function ChroniclePage({ params }: { params: Promise<{ id: string }> }) {
  const [id, setId] = useState("");
  const [entry, setEntry] = useState<Chronicle | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async (chronicleId: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/chronicles/${encodeURIComponent(chronicleId)}`, { cache: "no-store" });
      if (!response.ok) throw new Error(response.status === 404 ? "This chronicle could not be found." : "The chronicle service is unavailable.");
      const parsed = chronicleSchema.safeParse(await response.json());
      if (!parsed.success) throw new Error("This chronicle has an invalid response.");
      setEntry(parsed.data); setError("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Unable to load this chronicle."); }
  }, []);
  useEffect(() => { let active = true; void params.then(({ id: value }) => { if (active) { setId(value); void load(value); } }); return () => { active = false; }; }, [params, load]);
  const recap = record(entry?.recap);
  const mvp = record(recap.mvp_categories);
  async function share() {
    const url = window.location.href;
    try { if (navigator.share) await navigator.share({ title: entry?.title ?? "MythosLive Chronicle", url }); else await navigator.clipboard.writeText(url); }
    catch { await navigator.clipboard.writeText(url); }
  }
  return <main className="min-h-screen bg-[#10141b] px-5 py-10 text-[#f4ead7] sm:px-8"><article className="mx-auto max-w-4xl overflow-hidden rounded-2xl border border-amber-200/20 bg-[#171c24] shadow-2xl shadow-black/40"><header className="border-b border-amber-100/10 bg-[radial-gradient(ellipse_at_top,#80541f44,transparent_70%)] px-7 py-10 text-center sm:px-14"><Link href="/" className="text-xs font-bold tracking-[.25em] text-amber-200">✦ MYTHOSLIVE CHRONICLES</Link><p className="mt-9 text-xs uppercase tracking-[.25em] text-amber-300">A TALE FROM EMBERFALL</p><h1 className="mt-3 font-serif text-4xl md:text-6xl">{entry?.title ?? "The sealed chronicle"}</h1>{entry && <p className="mt-4 text-sm text-slate-400">Recorded {new Date(entry.created_at).toLocaleDateString()}</p>}<button onClick={() => void share()} disabled={!entry} className="mt-7 rounded-lg border border-amber-200/30 px-5 py-2 text-sm font-semibold text-amber-100 disabled:opacity-50">Share this chronicle</button></header>
    {error ? <div role="alert" className="p-10 text-center text-rose-200">{error}</div> : !entry ? <div className="p-10 text-center text-slate-400">Opening the book…</div> : <div className="space-y-9 px-7 py-9 sm:px-14"><p className="text-center text-slate-300">{String(recap.party_size ?? 0)} adventurers stood together.</p><section><h2 className="font-serif text-2xl text-amber-100">Key moments</h2><ul className="mt-4 space-y-3">{list(recap.key_moments).map((moment, index) => <li key={index} className="rounded-lg border border-white/10 bg-black/15 p-4 text-slate-200">✧ {String(moment)}</li>)}</ul></section><section><h2 className="font-serif text-2xl text-amber-100">Hall of heroes</h2><div className="mt-4 flex flex-wrap gap-3">{Object.entries(mvp).filter(([, name]) => typeof name === "string" && name).map(([category, name]) => <span key={category} className="rounded-full border border-amber-200/20 bg-amber-300/5 px-4 py-2 text-sm"><b className="capitalize text-amber-200">{category}:</b> {String(name)}</span>)}</div></section><section><h2 className="font-serif text-2xl text-amber-100">The next page</h2><p className="mt-3 rounded-lg border border-violet-200/20 bg-violet-300/5 p-5 text-slate-200">{String(recap.cliffhanger ?? "Emberfall's story continues…")}</p></section><p className="border-t border-white/10 pt-5 text-center text-xs text-slate-500">A public campaign recap. Private chat transcripts and account credentials are never included.</p></div>}</article><p className="mx-auto mt-6 max-w-4xl text-center text-sm text-slate-500">{id && `Chronicle ${id.slice(0, 8)}`} · <Link className="text-amber-200 underline" href="/">Begin a tale of your own</Link></p></main>;
}
