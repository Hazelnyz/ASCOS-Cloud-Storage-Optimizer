import { Menu, LogOut, UserRound } from 'lucide-react'
import { useAuth } from '@/context/authContext'
import { Dropdown } from '@/components/common/Dropdown'

function initials(email: string, displayName: string | null): string {
  const source = (displayName ?? email).trim()
  if (!source) return '?'
  const parts = source.split(/[\s@._-]+/).filter(Boolean)
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : source.slice(0, 2)).toUpperCase()
}

export function Topbar({ title, onOpenMobileNav }: { title: string; onOpenMobileNav: () => void }) {
  const { user, signOut } = useAuth()
  const primaryLabel = user?.displayName ?? user?.email ?? ''

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-surface-border bg-surface-raised px-4">
      <button
        onClick={onOpenMobileNav}
        className="focus-ring rounded-md p-1.5 text-slate-400 hover:bg-white/5 hover:text-slate-200 md:hidden"
        aria-label="Open navigation menu"
      >
        <Menu className="h-5 w-5" aria-hidden="true" />
      </button>

      <h1 className="text-sm font-semibold text-slate-100">{title}</h1>

      <div className="ml-auto flex items-center gap-2">
        {user && (
          <Dropdown
            label={`Account menu for ${primaryLabel || 'your account'}`}
            trigger={
              <span className="flex items-center gap-2 rounded-lg px-1.5 py-0.5">
                <span className="grid h-7 w-7 place-items-center rounded-full bg-indigo-500/20 text-xs font-semibold text-indigo-300" aria-hidden="true">
                  {initials(user.email, user.displayName)}
                </span>
                <span className="hidden max-w-[12rem] truncate text-xs text-slate-300 sm:inline">{primaryLabel}</span>
              </span>
            }
            items={[
              {
                label: user.displayName ? `${user.displayName} · ${user.email}` : user.email || 'Signed in',
                onSelect: () => {},
                icon: <UserRound className="h-3.5 w-3.5" aria-hidden="true" />,
                disabled: true,
              },
              { label: 'Sign out', onSelect: () => void signOut(), icon: <LogOut className="h-3.5 w-3.5" aria-hidden="true" />, danger: true },
            ]}
          />
        )}
      </div>
    </header>
  )
}
