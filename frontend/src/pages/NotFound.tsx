import { Link } from 'react-router-dom'
import { Compass } from 'lucide-react'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'

export function NotFound() {
  useDocumentTitle('Page not found')
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
      <div className="rounded-full bg-white/5 p-3 text-slate-400"><Compass className="h-6 w-6" aria-hidden="true" /></div>
      <h2 className="text-lg font-semibold text-slate-100">Page not found</h2>
      <p className="max-w-sm text-sm text-slate-400">That address does not match any page in ASCOS. The link may be old or mistyped.</p>
      <Link to="/" className="focus-ring rounded-lg border border-surface-border bg-surface-card px-3.5 py-2 text-sm font-medium text-slate-200 hover:bg-white/5">
        Back to the dashboard
      </Link>
    </div>
  )
}
