import { Settings2 } from 'lucide-react'

/** Shown instead of the app when required configuration is missing/invalid. Lists variable NAMES only. */
export function ConfigError({ problems }: { problems: string[] }) {
  return (
    <div role="alert" className="flex min-h-screen items-center justify-center bg-surface px-4">
      <div className="w-full max-w-lg rounded-xl border border-amber-500/25 bg-surface-card p-6 shadow-panel">
        <div className="mb-3 flex items-center gap-2 text-amber-400">
          <Settings2 className="h-5 w-5" aria-hidden="true" />
          <h1 className="text-base font-semibold">ASCOS is not configured</h1>
        </div>
        <p className="mb-3 text-sm text-slate-300">
          This build is missing required configuration, so it will not start. It never falls back to demo data.
        </p>
        <ul className="mb-3 list-disc space-y-1 pl-5 text-sm text-slate-300">
          {problems.map((p) => <li key={p}>{p}</li>)}
        </ul>
        <p className="text-xs text-slate-400">Set the VITE_* variables described in .env.example and rebuild.</p>
      </div>
    </div>
  )
}
