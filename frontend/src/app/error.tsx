"use client";

export default function RouteError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <main className="mx-auto grid min-h-screen max-w-xl content-center gap-4 px-6">
    <p className="text-xs font-bold uppercase tracking-[.2em] text-amber-300">MYTHOSLIVE</p>
    <h1 className="text-3xl font-semibold">This part of the adventure hit a snag.</h1>
    <p className="text-slate-300">Your saved campaign is still safe. Try loading this page again.</p>
    <button onClick={reset} className="w-fit rounded-lg bg-amber-300 px-4 py-2 font-semibold text-slate-950">Try again</button>
  </main>;
}
