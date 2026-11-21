import { useEffect, useState } from 'react'
import { Modal } from '@/components/common/Modal'
import { Button } from '@/components/common/Button'
import { TierBadge } from '@/components/common/TierBadge'
import { toUserMessage } from '@/services/errors'
import { TIER_STORAGE_CLASS, type StorageTier, type TierChangeResult } from '@/types'

const TIER_ORDER: StorageTier[] = ['HOT', 'WARM', 'COLD']

interface TierChangeDialogProps {
  open: boolean
  onClose: () => void
  filename: string
  currentTier: StorageTier | null
  /** Known from this session's own actions only - defaults to "not protected" until learned otherwise. See Files page notes. */
  protectedHint: boolean
  onSubmit: (targetTier: StorageTier) => Promise<TierChangeResult>
  onChanged: (result: TierChangeResult) => void
}

export function TierChangeDialog({
  open, onClose, filename, currentTier, protectedHint, onSubmit, onChanged,
}: TierChangeDialogProps) {
  const [target, setTarget] = useState<StorageTier | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Reset selection each time the dialog opens for a (possibly different) file.
  useEffect(() => {
    if (open) {
      setTarget(null)
      setError(null)
    }
  }, [open])

  async function handleConfirm() {
    if (!target) return
    setBusy(true)
    setError(null)
    try {
      const result = await onSubmit(target)
      onChanged(result)
      onClose()
    } catch (err) {
      setError(toUserMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Change tier — ${filename}`}
      dismissible={!busy}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="primary" onClick={() => void handleConfirm()} loading={busy} disabled={!target || target === currentTier}>
            Confirm change
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-xs text-slate-400">
          Current tier: {currentTier ? <TierBadge tier={currentTier} showClass /> : <span>unknown</span>}
        </div>

        <div className="space-y-2" role="radiogroup" aria-label="Target tier">
          {TIER_ORDER.map((tier) => {
            const isCurrent = tier === currentTier
            const isSelected = tier === target
            return (
              <button
                key={tier}
                type="button"
                role="radio"
                aria-checked={isSelected}
                disabled={busy}
                onClick={() => setTarget(tier)}
                className={`focus-ring flex w-full items-center justify-between rounded-xl border px-4 py-3 text-left transition-colors disabled:opacity-50 ${
                  isSelected ? 'border-accent bg-accent/10 ring-1 ring-accent/40' : 'border-surface-border hover:bg-white/[0.03]'
                }`}
              >
                <span className="flex items-center gap-2">
                  <TierBadge tier={tier} />
                  <span className="text-xs text-slate-500">· {TIER_STORAGE_CLASS[tier]}</span>
                </span>
                {isCurrent && <span className="text-xs text-slate-500">Current</span>}
              </button>
            )
          })}
        </div>

        {target && target === currentTier && (
          <p role="status" className="text-sm text-amber-400">No action needed — file is already at this tier.</p>
        )}

        {/* Honest placeholder: forecast-fn is still the Stage 5 scaffold, no real
            cost numbers exist yet. Shown only once a target is picked, matching
            where the master reference's real forecast step would appear. */}
        {target && target !== currentTier && (
          <div className="rounded-lg border border-dashed border-surface-border px-3 py-2 text-xs text-slate-500">
            Cost forecast — not available yet.
          </div>
        )}

        {protectedHint && (
          <p className="text-xs text-slate-500">
            This file is pinned. Manual tier changes are still allowed — pinning only blocks automated ML-driven changes.
          </p>
        )}

        {error && (
          <p role="alert" className="rounded-md border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        )}
      </div>
    </Modal>
  )
}
