import { Pin } from 'lucide-react'

export function ProtectedBadge({ compact = false }: { compact?: boolean }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border border-accent/30 bg-accent/10 px-2 py-0.5 text-xs font-medium text-indigo-300"
      title="Pinned - excluded from automated ML-driven tier changes"
    >
      <Pin className="h-3 w-3 rotate-45" aria-hidden="true" />
      {!compact && 'Pinned'}
    </span>
  )
}
