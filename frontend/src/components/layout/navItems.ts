import {
  LayoutDashboard, Files, Sparkles, ShieldCheck, BarChart3, ShieldAlert, Wallet, Settings,
} from 'lucide-react'

export const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/files', label: 'My Files', icon: Files, end: false },
  { to: '/predictions', label: 'AI Predictions', icon: Sparkles, end: false },
  { to: '/protected', label: 'Protected Files', icon: ShieldCheck, end: false },
  { to: '/analytics', label: 'Analytics', icon: BarChart3, end: false },
  { to: '/security', label: 'Security', icon: ShieldAlert, end: false },
  { to: '/budget', label: 'Cost & Budget', icon: Wallet, end: false },
  { to: '/settings', label: 'Settings', icon: Settings, end: false },
] as const

export function titleForPath(pathname: string): string | null {
  const match = NAV_ITEMS.find((i) => (i.end ? pathname === i.to : pathname === i.to || pathname.startsWith(`${i.to}/`)))
  return match?.label ?? null
}
