"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { useCallback, useEffect, useState } from "react";
import { z } from "zod";
import { apiFetch } from "@/lib/api";
import { API_BASE_URL } from "@/lib/runtime-config";

const statusSchema = z.object({
  broadcaster_connected: z.boolean(), bot_connected: z.boolean(),
  broadcaster_user_id: z.string().nullable(), bot_user_id: z.string().nullable(),
  broadcaster_scopes: z.array(z.string()), bot_scopes: z.array(z.string()),
  eventsub_status: z.enum(["disconnected", "connecting", "connected", "degraded"]),
  eventsub_session_id: z.string().nullable(), subscriptions: z.record(z.string(), z.string()),
  last_keepalive_at: z.string().nullable(), last_message_at: z.string().nullable(),
  last_error: z.string().nullable(), chat_send_enabled: z.boolean(),
  outbox_pending: z.number(), outbox_sent: z.number(), outbox_dropped: z.number(),
});
const authSchema = z.object({ authenticated: z.boolean(), mode: z.enum(["twitch", "simulator"]).optional() });
const optionsSchema = z.object({ simulator_available: z.boolean(), twitch_configured: z.boolean() });
const apiBase = API_BASE_URL;

function Card({ title, children }: { title: string; children: ReactNode }) {
  return <section className="rounded-2xl border border-white/10 bg-[#161a23] p-5 shadow-[0_14px_50px_#05060955]"><h2 className="text-sm font-bold uppercase tracking-[.18em] text-[#d8b66e]">{title}</h2><div className="mt-4">{children}</div></section>;
}

export default function ConnectPage() {
  const router = useRouter();
  const [auth, setAuth] = useState<{ authenticated: boolean; mode?: "twitch" | "simulator" } | null>(null);
  const [options, setOptions] = useState<z.infer<typeof optionsSchema> | null>(null);
  const [status, setStatus] = useState<z.infer<typeof statusSchema> | null>(null);
  const [error, setError] = useState("");
  const [overlayUrl, setOverlayUrl] = useState("");
  const [overlayKey, setOverlayKey] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const session = await apiFetch("/api/dashboard/auth", authSchema);
      setAuth({ authenticated: session.authenticated, mode: session.mode });
      setStatus(await apiFetch("/api/twitch/status", statusSchema));
      setError("");
    } catch {
      setAuth({ authenticated: false });
      setStatus(null);
    }
    try { setOptions(await apiFetch("/api/dashboard/auth-options", optionsSchema)); } catch { /* backend offline state shown below */ }
  }, []);
  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 5000); return () => window.clearInterval(timer); }, [load]);

  async function simulatorLogin() {
    setBusy(true);
    try {
      await apiFetch("/api/dashboard/dev-session", z.object({ status: z.string() }), { method: "POST" });
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Simulator sign-in failed."); }
    finally { setBusy(false); }
  }

  async function startJudgeDemo() {
    setBusy(true); setError("");
    try {
      await apiFetch("/api/dashboard/dev-session", z.object({ status: z.string() }), { method: "POST" });
      await apiFetch("/api/sim/start", z.object({ simulated: z.literal(true) }), { method: "POST" });
      router.push("/sim");
    } catch (e) { setError(e instanceof Error ? e.message : "Could not start the local Emberfall demo."); }
    finally { setBusy(false); }
  }

  async function request(path: string, method: "POST" | "DELETE", body?: unknown) {
    setBusy(true);
    try {
      const result = await apiFetch(path, z.record(z.string(), z.unknown()), {
        method, headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
      if (path === "/api/overlay/key") {
        const key = String(result.key);
        setOverlayKey(key);
        const url = new URL("/overlay", window.location.origin);
        url.searchParams.set("key", key);
        url.searchParams.set("layout", "bottom");
        setOverlayUrl(url.toString());
      } else if (method === "DELETE") {
        setOverlayKey(""); setOverlayUrl("");
      }
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Request failed."); }
    finally { setBusy(false); }
  }

  async function signout() {
    try { await apiFetch("/api/dashboard/signout", z.object({ status: z.string() }), { method: "POST" }); }
    catch { /* expired sessions are cleared by refresh */ }
    setAuth({ authenticated: false }); setStatus(null);
  }

  if (auth?.authenticated !== true) return <main className="mx-auto flex min-h-screen max-w-5xl items-center px-6 py-12"><div className="w-full rounded-3xl border border-white/10 bg-[#171b24] p-8 shadow-2xl md:p-12"><p className="text-xs font-bold uppercase tracking-[.24em] text-[#d8b66e]">MythosLive · Control Room</p><h1 className="mt-4 max-w-2xl text-4xl font-semibold leading-tight">Your channel, your Chronicle.</h1><p className="mt-4 max-w-2xl text-slate-400">Sign in with the broadcaster account to manage a channel. Simulator access is local-only and never connects to Twitch.</p>{error && <p role="alert" className="mt-5 rounded-xl border border-rose-500/30 bg-rose-950/40 p-3 text-rose-200">{error}</p>}<div className="mt-8 flex flex-wrap gap-3">{options?.twitch_configured && <a className="rounded-xl bg-[#d8b66e] px-5 py-3 font-semibold text-[#17130d]" href={`${apiBase}/api/twitch/oauth/broadcaster/start`}>Continue with Twitch</a>}{options?.simulator_available && <><button disabled={busy} onClick={() => void startJudgeDemo()} className="rounded-xl bg-emerald-500 px-5 py-3 font-semibold text-slate-950 hover:bg-emerald-400 disabled:opacity-50">{busy ? "Starting Emberfall…" : "Start judge demo"}</button><button disabled={busy} onClick={() => void simulatorLogin()} className="rounded-xl border border-white/15 bg-white/5 px-5 py-3 font-semibold hover:bg-white/10 disabled:opacity-50">Enter simulator control room</button></>}</div>{!options?.twitch_configured && <p className="mt-5 text-sm text-slate-500">Twitch OAuth is unavailable until client credentials and exact callback URLs are configured.</p>}<Link className="mt-8 inline-block text-sm text-slate-400 underline underline-offset-4" href="/">Return to MythosLive</Link></div></main>;

  const statusLine = (connected: boolean) => <span className={`inline-flex items-center gap-2 text-sm ${connected ? "text-emerald-300" : "text-slate-400"}`}><i className={`h-2 w-2 rounded-full ${connected ? "bg-emerald-400" : "bg-slate-500"}`} />{connected ? "Connected" : "Not connected"}</span>;
  const accountCard = (role: "broadcaster" | "bot", connected: boolean, userId: string | null, scopes: string[]) => <Card title={`${role} account`} key={role}><div className="flex items-center justify-between">{statusLine(connected)}<span className="text-xs uppercase tracking-wider text-slate-500">{role === "broadcaster" ? "Channel owner" : "Chat co-host"}</span></div>{userId && <p className="mt-3 text-sm text-slate-300">Twitch ID · {userId}</p>}<p className="mt-3 text-xs leading-relaxed text-slate-500">Required scopes: {role === "broadcaster" ? "channel:bot, moderator:read:followers" : "user:read:chat, user:write:chat, user:bot"}</p>{scopes.length > 0 && <p className="mt-2 break-words text-xs text-emerald-200/80">Granted · {scopes.join(" · ")}</p>}<div className="mt-5">{connected ? <button disabled={busy} onClick={() => void request(`/api/twitch/oauth/${role}`, "DELETE")} className="rounded-lg border border-white/15 px-4 py-2 text-sm hover:bg-white/5">Disconnect {role}</button> : <a className="inline-block rounded-lg bg-white/10 px-4 py-2 text-sm font-semibold hover:bg-white/15" href={`${apiBase}/api/twitch/oauth/${role}/start`}>Connect {role}</a>}</div></Card>;

  return <main className="mx-auto min-h-screen max-w-7xl space-y-6 px-5 py-7 md:px-8"><header className="flex flex-wrap items-end justify-between gap-4"><div><Link href="/dashboard" className="text-xs font-bold uppercase tracking-[.2em] text-[#d8b66e]">← Control Room</Link><h1 className="mt-3 text-3xl font-semibold">Connections & OBS</h1><p className="mt-1 text-sm text-slate-400">Signed in · {auth.mode === "simulator" ? "local simulator" : "broadcaster session"}</p></div><button onClick={() => void signout()} className="rounded-lg border border-white/10 px-4 py-2 text-sm text-slate-300">Sign out</button></header>
    {error && <p role="alert" className="rounded-xl border border-rose-500/30 bg-rose-950/40 p-3 text-rose-200">{error}</p>}
    {auth.mode === "simulator" ? <Card title="Simulator mode"><p className="text-sm leading-relaxed text-slate-300">Twitch connections and chat sending are disabled in simulator mode. No simulator event can be sent to a real channel.</p></Card> : <><p className="text-sm text-slate-400">Authorize the broadcaster first, then authorize a bot account for that same channel. Tokens remain server-side and are never returned here.</p><div className="grid gap-4 md:grid-cols-2">{status && <>{accountCard("broadcaster", status.broadcaster_connected, status.broadcaster_user_id, status.broadcaster_scopes)}{accountCard("bot", status.bot_connected, status.bot_user_id, status.bot_scopes)}</>}</div><Card title="EventSub connection"><div className="grid gap-4 sm:grid-cols-2"><div><p className="text-xs uppercase tracking-wider text-slate-500">Connection</p><p className="mt-1 text-lg capitalize">{status?.eventsub_status ?? "Loading"}</p><p className="mt-3 text-xs text-slate-500">Session {status?.eventsub_session_id ?? "—"}</p></div><div className="space-y-1 text-sm text-slate-400"><p>Last keepalive · {status?.last_keepalive_at ?? "Not received"}</p><p>Last message · {status?.last_message_at ?? "Not received"}</p></div></div><div className="mt-4 flex flex-wrap gap-2">{Object.entries(status?.subscriptions ?? {}).map(([name, value]) => <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs" key={name}>{name} · {value}</span>)}</div>{status?.last_error && <p className="mt-4 rounded-lg bg-amber-950/40 p-3 text-sm text-amber-200">{status.last_error} · Verify callback URLs, granted scopes, bot channel access, and broadcaster/bot identity matching.</p>}</Card>
    <Card title="Bot response outbox"><p className="text-sm text-slate-400">Sending is disabled until explicitly enabled. A test response requires both accounts and is reported by Twitch as sent or dropped.</p><button disabled={!status?.broadcaster_connected || !status.bot_connected || busy} onClick={() => void request("/api/twitch/chat/enable", "POST", { enabled: !status?.chat_send_enabled })} className="mt-4 rounded-lg bg-[#d8b66e] px-4 py-2 font-semibold text-[#17130d] disabled:opacity-40">{status?.chat_send_enabled ? "Disable bot replies" : "Explicitly enable bot replies"}</button><div className="mt-3 text-xs text-slate-500">Queue {status?.outbox_pending ?? 0} · sent {status?.outbox_sent ?? 0} · dropped {status?.outbox_dropped ?? 0}</div></Card></>}
    <Card title="OBS browser source"><p className="text-sm text-slate-400">Create a revocable read-only key scoped to this channel. It cannot access the dashboard.</p><div className="mt-4 flex flex-wrap gap-3"><button disabled={busy} onClick={() => void request("/api/overlay/key", "POST", {})} className="rounded-lg bg-violet-500 px-4 py-2 text-sm font-semibold">{overlayKey ? "Rotate overlay key" : "Create overlay key"}</button>{overlayKey && <button disabled={busy} onClick={() => void request("/api/overlay/key", "DELETE")} className="rounded-lg border border-rose-500/30 px-4 py-2 text-sm text-rose-200">Revoke key</button>}</div>{overlayUrl && <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]"><div><div className="flex gap-2"><input readOnly value={overlayUrl} className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs"/><button onClick={() => void navigator.clipboard.writeText(overlayUrl)} className="rounded-lg bg-white/10 px-3 text-sm">Copy</button></div><p className="mt-2 text-xs text-slate-500">Treat this URL as a view-only secret. Revoke it here if shared accidentally.</p></div><iframe title="OBS overlay mini preview" src={overlayUrl} className="aspect-video w-full overflow-hidden rounded-xl border border-white/10 bg-transparent" /></div>}</Card>
  </main>;
}
