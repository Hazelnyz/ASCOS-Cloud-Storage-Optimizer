import type { ReactNode } from 'react'

export function EmptyState({ icon, title, description }: { icon: ReactNode; title: string; description?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-surface-border py-14 text-center">
      <div className="rounded-full bg-white/5 p-3 text-slate-400">{icon}</div>
      <p className="text-sm font-medium text-slate-200">{title}</p>
      {description && <p className="max-w-sm text-xs text-slate-500">{description}</p>}
    </div>
  )
}
