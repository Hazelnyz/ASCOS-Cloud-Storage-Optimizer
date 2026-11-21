import type { ReactNode } from 'react'

interface MetricCardProps {
  label: string
  value: string
  icon: ReactNode
  hint?: string
  trend?: { direction: 'up' | 'down'; label: string }
  onClick?: () => void
}

export function MetricCard({ label, value, icon, hint, trend, onClick }: MetricCardProps) {
  return (
    <div 
      className={`rounded-xl border border-surface-border bg-surface-card p-4 shadow-panel ${onClick ? 'cursor-pointer hover:border-slate-500 transition-colors' : ''}`}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      <div className="flex items-start justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
        <div className="rounded-lg bg-white/5 p-1.5 text-slate-300">{icon}</div>
      </div>
      <p className="mt-2 text-2xl font-semibold text-slate-50">{value}</p>
      <div className="mt-1 flex items-center gap-2">
        {trend && (
          <span className={`text-xs font-medium ${trend.direction === 'up' ? 'text-emerald-400' : 'text-rose-400'}`}>
            {trend.direction === 'up' ? '↑' : '↓'} {trend.label}
          </span>
        )}
        {hint && <span className="text-xs text-slate-500">{hint}</span>}
      </div>
    </div>
  )
}
