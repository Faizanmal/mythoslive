"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { z } from "zod";
import { apiFetch } from "@/lib/api";

const authSchema = z.object({ authenticated: z.literal(true), mode: z.enum(["twitch", "simulator"]) });
const optionsSchema = z.object({ simulator_available: z.boolean(), twitch_configured: z.boolean() });

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [ready, setReady] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [simAvailable, setSimAvailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const connectPage = pathname === "/dashboard/connect";
  const refresh = useCallback(async () => {
    try { await apiFetch("/api/dashboard/auth", authSchema); setAuthenticated(true); }
    catch { setAuthenticated(false); }
    try { setSimAvailable((await apiFetch("/api/dashboard/auth-options", optionsSchema)).simulator_available); }
    catch { setError("The MythosLive API is offline."); }
    setReady(true);
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  if (connectPage || (ready && authenticated)) return <>{children}</>;
  if (!ready) return <main className="grid min-h-screen place-items-center text-sm text-slate-400">Opening your control room…</main>;
  async function enterSimulator() {
    setBusy(true); setError("");
    try { await apiFetch("/api/dashboard/dev-session", z.object({ status: z.string() }), { method: "POST" }); await refresh(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Simulator sign-in failed."); }
    finally { setBusy(false); }
  }
  return <main className="mx-auto flex min-h-screen max-w-4xl items-center px-6 py-12"><section className="w-full rounded-3xl border border-white/10 bg-[#171b24] p-8 md:p-12"><p className="text-xs font-bold uppercase tracking-[.2em] text-[#d8b66e]">Protected control room</p><h1 className="mt-4 text-3xl font-semibold">Broadcaster sign-in required</h1><p className="mt-3 text-slate-400">Dashboard data and controls require the authenticated broadcaster session. Overlay keys only grant read-only overlay access.</p>{error && <p role="alert" className="mt-4 text-rose-300">{error}</p>}<div className="mt-7 flex flex-wrap gap-3"><Link href="/dashboard/connect" className="rounded-xl bg-[#d8b66e] px-5 py-3 font-semibold text-[#17130d]">Connect broadcaster</Link>{simAvailable && <button onClick={() => void enterSimulator()} disabled={busy} className="rounded-xl border border-white/15 px-5 py-3 font-semibold disabled:opacity-50">{busy ? "Signing in…" : "Enter simulator mode"}</button>}</div><Link className="mt-7 inline-block text-sm text-slate-400 underline" href="/">Back to MythosLive</Link></section></main>;
}
