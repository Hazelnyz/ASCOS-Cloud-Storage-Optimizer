import { Pin, Trash2, X } from 'lucide-react'
import { Button } from '@/components/common/Button'

interface SelectionActionBarProps {
  count: number
  onDelete: () => void
  onClear: () => void
  /** Pin every selected file that is not pinned yet. Omit when nothing selected can be pinned. */
  onPin?: () => void
  pinBusy?: boolean
}

export function SelectionActionBar({ count, onDelete, onClear, onPin, pinBusy = false }: SelectionActionBarProps) {
  if (count === 0) return null
  return (
    <div
      role="toolbar"
      aria-label="Selected files actions"
      className="sticky top-0 z-10 mb-3 flex items-center justify-between rounded-lg border border-accent/30 bg-accent/10 px-3 py-2"
    >
      <p className="text-xs font-medium text-indigo-200">{count} file{count === 1 ? '' : 's'} selected</p>
      <div className="flex items-center gap-2">
        {onPin && (
          <Button variant="secondary" size="sm" icon={<Pin className="h-3.5 w-3.5 rotate-45" />} onClick={onPin} loading={pinBusy}>Pin</Button>
        )}
        <Button variant="danger" size="sm" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={onDelete} disabled={pinBusy}>Delete</Button>
        <Button variant="ghost" size="sm" icon={<X className="h-3.5 w-3.5" />} onClick={onClear} disabled={pinBusy}>Clear</Button>
      </div>
    </div>
  )
}
