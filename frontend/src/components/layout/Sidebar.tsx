import { NavLink } from 'react-router-dom'
import { Cloud, ChevronsLeft, ChevronsRight, Settings } from 'lucide-react'
import { useState } from 'react'
import { NAV_ITEMS } from './navItems'

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false)
  const primaryItems = NAV_ITEMS.filter((i) => i.to !== '/settings')

  return (
    <aside
      className={`hidden shrink-0 flex-col border-r border-surface-border bg-surface-raised transition-all duration-200 md:flex ${collapsed ? 'w-16' : 'w-60'}`}
    >
      <div className="flex h-14 items-center gap-2 border-b border-surface-border px-4">
        <div className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-accent text-white">
          <Cloud className="h-4 w-4" />
        </div>
        {!collapsed && <span className="text-sm font-semibold tracking-wide text-slate-100">ASCOS</span>}
      </div>

      <nav className="flex-1 space-y-0.5 px-2 py-3" aria-label="Primary">
        {primaryItems.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            title={collapsed ? label : undefined}
            className={({ isActive }) =>
              `focus-ring flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-accent/15 text-indigo-300'
                  : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'
              }`
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            {!collapsed && <span>{label}</span>}
          </NavLink>
        ))}
      </nav>

      <div className="space-y-0.5 border-t border-surface-border px-2 py-3">
        <NavLink
          to="/settings"
          title={collapsed ? 'Settings' : undefined}
          className={({ isActive }) =>
            `focus-ring flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors ${
              isActive ? 'bg-accent/15 text-indigo-300' : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'
            }`
          }
        >
          <Settings className="h-4 w-4 shrink-0" />
          {!collapsed && <span>Settings</span>}
        </NavLink>
        <button
          onClick={() => setCollapsed((v) => !v)}
          className="focus-ring flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium text-slate-500 hover:bg-white/5 hover:text-slate-300"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
          {!collapsed && <span>Collapse</span>}
        </button>
      </div>
    </aside>
  )
}
