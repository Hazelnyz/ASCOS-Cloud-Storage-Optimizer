import { AlertTriangle } from 'lucide-react'
import { Button } from './Button'
import { toUserMessage } from '@/services/errors'

/** Accepts the caught error itself so raw messages can never be rendered. */
export function ErrorState({ error, onRetry, title = 'Something went wrong' }: { error: unknown; onRetry?: () => void; title?: string }) {
  return (
    <div role="alert" className="flex flex-col items-center justify-center gap-3 rounded-xl border border-rose-500/20 bg-rose-500/5 py-12 text-center">
      <AlertTriangle className="h-6 w-6 text-rose-400" aria-hidden="true" />
      <p className="text-sm font-medium text-slate-200">{title}</p>
      <p className="max-w-sm text-sm text-slate-300">{toUserMessage(error)}</p>
      {onRetry && <Button variant="secondary" size="sm" onClick={onRetry}>Try again</Button>}
    </div>
  )
}
