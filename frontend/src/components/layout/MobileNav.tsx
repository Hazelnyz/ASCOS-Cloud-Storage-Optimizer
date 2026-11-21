import { useRef } from 'react'
import { NavLink } from 'react-router-dom'
import { X, Cloud } from 'lucide-react'
import { NAV_ITEMS } from './navItems'
import { useFocusTrap } from '@/hooks/useFocusTrap'

export function MobileNav({ open, onClose }: { open: boolean; onClose: () => void }) {
  const panelRef = useRef<HTMLDivElement>(null)
  useFocusTrap(panelRef, open, onClose)
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 md:hidden">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Navigation menu"
        className="absolute inset-y-0 left-0 w-64 border-r border-surface-border bg-surface-raised"
      >
        <div className="flex h-14 items-center justify-between border-b border-surface-border px-4">
          <div className="flex items-center gap-2">
            <div className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-white">
              <Cloud className="h-4 w-4" aria-hidden="true" />
            </div>
            <span className="text-sm font-semibold text-slate-100">ASCOS</span>
          </div>
          <button onClick={onClose} className="focus-ring rounded text-slate-400 hover:text-slate-200" aria-label="Close menu">
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <nav className="space-y-0.5 px-2 py-3" aria-label="Mobile primary">
          {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              onClick={onClose}
              className={({ isActive }) =>
                `focus-ring flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium ${
                  isActive ? 'bg-accent/15 text-indigo-300' : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'
                }`
              }
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
              {label}
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  )
}
