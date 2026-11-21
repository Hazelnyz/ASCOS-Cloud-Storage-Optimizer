import { useId, useRef, type ReactNode } from 'react'
import { Pin, PinOff, X } from 'lucide-react'
import { Button } from '@/components/common/Button'
import { TierBadge } from '@/components/common/TierBadge'
import { ProtectedBadge } from '@/components/common/ProtectedBadge'
import { LoadingState } from '@/components/common/LoadingState'
import { fileKindLabel } from '@/components/files/FileTypeIcon'
import { useFocusTrap } from '@/hooks/useFocusTrap'
import { formatBytes, formatDateTime } from '@/lib/format'
import { tierFromStorageClass, type FileMetadata } from '@/types'

function Row({ label, value, muted = false, title }: { label: string; value: ReactNode; muted?: boolean; title?: string }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className={`text-right tabular-nums ${muted ? 'text-slate-500' : 'font-semibold text-slate-100'}`} title={title}>{value}</span>
    </div>
  )
}

function Card({ children }: { children: ReactNode }) {
  return <section className="divide-y divide-surface-border/60 rounded-xl border border-surface-border bg-surface-card/60 px-4">{children}</section>
}

interface FileDetailsDialogProps {
  open: boolean
  onClose: () => void
  filename: string
  metadata: FileMetadata | null
  metadataError: string | null
  /** Known from this session's own actions only - defaults to "not protected" until learned otherwise. See Files page notes. */
  isProtected: boolean
  protectBusy: boolean
  onToggleProtect: () => void
}

/** Right-hand slide-over with the file's details (named "Dialog" for import stability; it is a modal drawer). */
export function FileDetailsDialog({
  open, onClose, filename, metadata, metadataError, isProtected, protectBusy, onToggleProtect,
}: FileDetailsDialogProps) {
  const titleId = useId()
  const panelRef = useRef<HTMLDivElement>(null)
  useFocusTrap(panelRef, open, onClose)

  if (!open) return null

  const tier = metadata ? tierFromStorageClass(metadata.storageClass) : null
  const UNAVAILABLE = 'Unavailable'
  const ACCESS_HINT = 'Counts downloads and shares. New activity can take a few minutes to appear.'
  const accessUnknown = metadata ? metadata.recentAccessCount === null : true

  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col border-l border-surface-border bg-surface-raised shadow-2xl motion-safe:animate-slide-in"
      >
        <div className="flex items-center justify-between gap-3 border-b border-surface-border px-5 py-4">
          <h2 id={titleId} className="truncate text-sm font-semibold text-slate-100" title={filename}>{filename}</h2>
          <button onClick={onClose} className="focus-ring rounded p-1 text-slate-400 hover:bg-white/5 hover:text-slate-200" aria-label="Close details">
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
          {metadataError ? (
            <p role="alert" className="rounded-md border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">{metadataError}</p>
          ) : !metadata ? (
            <LoadingState rows={6} />
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                {tier && <TierBadge tier={tier} showClass />}
                {isProtected && <ProtectedBadge />}
              </div>

              <Card>
                <Row label="Size" value={formatBytes(metadata.size)} />
                <Row label="Type" value={fileKindLabel(metadata.filename)} />
                <Row label="Uploaded" value={metadata.uploadedAt ? formatDateTime(metadata.uploadedAt) : 'Not recorded (older file)'} muted={!metadata.uploadedAt} />
                <Row label="Last modified" value={(metadata.uploadedAt ?? metadata.lastModified) ? formatDateTime((metadata.uploadedAt ?? metadata.lastModified) as string) : '—'} muted={!(metadata.uploadedAt ?? metadata.lastModified)} />
                <Row
                  label="Last accessed"
                  value={accessUnknown ? UNAVAILABLE : metadata.lastAccessedAt ? formatDateTime(metadata.lastAccessedAt) : 'Never'}
                  muted={accessUnknown || !metadata.lastAccessedAt}
                  title={ACCESS_HINT}
                />
                <Row
                  label={`Accesses (${metadata.accessWindowDays ?? 30}d)`}
                  value={accessUnknown ? UNAVAILABLE : String(metadata.recentAccessCount)}
                  muted={accessUnknown || metadata.recentAccessCount === 0}
                  title={ACCESS_HINT}
                />
              </Card>

              {/* AI prediction section - shows real predictions when available */}
              <section className="rounded-xl border border-surface-border bg-surface-card/60 px-4 pb-3 pt-3.5">
                <div className="flex items-center justify-between">
                  <h3 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">AI prediction</h3>
                  <span className="rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                    Not available yet
                  </span>
                </div>
                <div className="divide-y divide-surface-border/60">
                  <Row label="P(access within 7 days)" value="—" muted />
                  <Row label="Candidate tier(s)" value="—" muted />
                  <Row label="Bandit choice" value="Not yet implemented" muted />
                </div>
                <p className="pt-2 text-xs text-slate-500">
                  {isProtected
                    ? 'Pinned files stay observable by the system but are excluded from automated tier changes. You can still move this file manually at any time.'
                    : 'Predictions appear here once the ML pipeline is connected.'}
                </p>
              </section>
            </>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-surface-border px-5 py-4">
          <Button variant="secondary" onClick={onClose}>Close</Button>
          <Button
            variant="primary"
            onClick={onToggleProtect}
            loading={protectBusy}
            icon={isProtected ? <PinOff className="h-4 w-4 rotate-45" aria-hidden="true" /> : <Pin className="h-4 w-4 rotate-45" aria-hidden="true" />}
          >
            {isProtected ? 'Unpin' : 'Pin'}
          </Button>
        </div>
      </div>
    </div>
  )
}
