import { useId, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { useFocusTrap } from '@/hooks/useFocusTrap'

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
  /** When false, Escape / backdrop / close button do nothing (e.g. while an action is running). */
  dismissible?: boolean
  size?: 'md' | 'lg'
}

export function Modal({ open, onClose, title, children, footer, dismissible = true, size = 'md' }: ModalProps) {
  const titleId = useId()
  const panelRef = useRef<HTMLDivElement>(null)
  const requestClose = dismissible ? onClose : undefined
  useFocusTrap(panelRef, open, requestClose ?? (() => {}))

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={requestClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`motion-safe:animate-fade-in relative max-h-[90vh] w-full overflow-y-auto rounded-xl border border-surface-border bg-surface-raised shadow-panel ${size === 'lg' ? 'max-w-xl' : 'max-w-md'}`}
      >
        <div className="flex items-center justify-between border-b border-surface-border px-5 py-3.5">
          <h2 id={titleId} className="text-sm font-semibold text-slate-100">{title}</h2>
          <button
            onClick={requestClose}
            disabled={!dismissible}
            className="focus-ring rounded text-slate-400 hover:text-slate-200 disabled:opacity-40"
            aria-label="Close dialog"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        <div className="px-5 py-4 text-sm text-slate-300">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-surface-border px-5 py-3.5">{footer}</div>}
      </div>
    </div>
  )
}
