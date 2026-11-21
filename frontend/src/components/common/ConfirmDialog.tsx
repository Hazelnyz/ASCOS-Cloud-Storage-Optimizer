import { type ReactNode } from 'react'
import { Modal } from './Modal'
import { Button } from './Button'

interface ConfirmDialogProps {
  open: boolean
  title: string
  children: ReactNode
  confirmLabel: string
  /** Defaults to 'danger' (destructive actions); use 'primary' for non-destructive confirmations. */
  confirmVariant?: 'danger' | 'primary'
  busy?: boolean
  /** Safe-to-display failure text; the dialog stays open so the user can retry. */
  error?: string | null
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({ open, title, children, confirmLabel, confirmVariant = 'danger', busy = false, error, onConfirm, onCancel }: ConfirmDialogProps) {
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={title}
      dismissible={!busy}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel} disabled={busy}>Cancel</Button>
          <Button variant={confirmVariant} onClick={onConfirm} loading={busy}>{confirmLabel}</Button>
        </>
      }
    >
      {children}
      {error && (
        <p role="alert" className="mt-3 rounded-md border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      )}
    </Modal>
  )
}
