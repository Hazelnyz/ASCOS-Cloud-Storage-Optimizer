import { Clock } from 'lucide-react'
import { CAPABILITIES, type CapabilityKey } from '@/lib/capabilities'

/** Honest "not live yet" panel driven by the capability manifest. */
export function CapabilityNotice({ capability, title, className = '' }: { capability: CapabilityKey; title?: string; className?: string }) {
  const c = CAPABILITIES[capability]
  return (
    <div className={`flex items-start gap-3 rounded-xl border border-dashed border-surface-border bg-surface-card/60 p-4 ${className}`}>
      <Clock className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
      <div>
        {title && <p className="text-sm font-medium text-slate-200">{title}</p>}
        <p className="text-xs text-slate-400">{c.reason}</p>
        <p className="mt-1 text-[11px] uppercase tracking-wide text-slate-500">Planned: {c.stage}</p>
      </div>
    </div>
  )
}
