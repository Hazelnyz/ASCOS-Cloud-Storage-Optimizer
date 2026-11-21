import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { CheckCircle2, XCircle, Info, X } from 'lucide-react'
import { ToastContext, type ToastKind } from './toastContext'

interface ToastItem { id: number; kind: ToastKind; message: string }

const ICONS: Record<ToastKind, ReactNode> = {
  success: <CheckCircle2 className="h-4 w-4 text-emerald-400" aria-hidden="true" />,
  error: <XCircle className="h-4 w-4 text-rose-400" aria-hidden="true" />,
  info: <Info className="h-4 w-4 text-sky-400" aria-hidden="true" />,
}

const AUTO_DISMISS_MS = 4500
const ERROR_DISMISS_MS = 8000

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>())
  const nextId = useRef(0)

  const dismiss = useCallback((id: number) => {
    const t = timers.current.get(id)
    if (t) clearTimeout(t)
    timers.current.delete(id)
    setItems((prev) => prev.filter((i) => i.id !== id))
  }, [])

  const show = useCallback((message: string, kind: ToastKind = 'success') => {
    const id = (nextId.current += 1)
    setItems((prev) => [...prev, { id, kind, message }])
    timers.current.set(id, setTimeout(() => dismiss(id), kind === 'error' ? ERROR_DISMISS_MS : AUTO_DISMISS_MS))
  }, [dismiss])

  // Clear every pending timer on unmount.
  useEffect(() => {
    const pending = timers.current
    return () => {
      pending.forEach((t) => clearTimeout(t))
      pending.clear()
    }
  }, [])

  const value = useMemo(() => ({ show }), [show])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        role="region"
        aria-label="Notifications"
        aria-live="polite"
        className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2"
      >
        {items.map((t) => (
          <div
            key={t.id}
            role={t.kind === 'error' ? 'alert' : 'status'}
            className="pointer-events-auto flex items-start gap-2 rounded-lg border border-surface-border bg-surface-raised px-3 py-2.5 shadow-panel"
          >
            {ICONS[t.kind]}
            <p className="flex-1 text-sm text-slate-200">{t.message}</p>
            <button
              onClick={() => dismiss(t.id)}
              className="focus-ring rounded text-slate-400 hover:text-slate-200"
              aria-label="Dismiss notification"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
