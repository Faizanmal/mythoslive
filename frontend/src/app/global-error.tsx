"use client";

export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <html lang="en"><body className="bg-slate-950 text-slate-100">
    <main className="mx-auto grid min-h-screen max-w-xl content-center gap-4 px-6">
      <h1 className="text-3xl font-semibold">MythosLive is having trouble starting.</h1>
      <p className="text-slate-300">The campaign data is stored separately. Please retry in a moment.</p>
      <button onClick={reset} className="w-fit rounded-lg bg-amber-300 px-4 py-2 font-semibold text-slate-950">Try again</button>
    </main>
  </body></html>;
}
