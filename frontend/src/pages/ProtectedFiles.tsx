import { useMemo, useState } from 'react'
import { ShieldCheck, ShieldOff } from 'lucide-react'
import { useAsyncData } from '@/hooks/useAsyncData'
import { useFileMetadata } from '@/hooks/useFileMetadata'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useToast } from '@/context/toastContext'
import { api } from '@/services/api'
import { toUserMessage } from '@/services/errors'
import { tierFromStorageClass, type FileSummary } from '@/types'
import { Button } from '@/components/common/Button'
import { CapabilityNotice } from '@/components/common/CapabilityNotice'
import { EmptyState } from '@/components/common/EmptyState'
import { ErrorState } from '@/components/common/ErrorState'
import { LoadingState } from '@/components/common/LoadingState'
import { TierBadge } from '@/components/common/TierBadge'
import { FileTypeIcon, fileKindLabel } from '@/components/files/FileTypeIcon'
import { formatBytes, formatDateTime, formatRelativeShort } from '@/lib/format'

function Stat({ label, value, muted = false, title }: { label: string; value: string; muted?: boolean; title?: string }) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <dt className="text-slate-500">{label}</dt>
      <dd className={`text-right tabular-nums ${muted ? 'text-slate-500' : 'font-medium text-slate-200'}`} title={title}>{value}</dd>
    </div>
  )
}

export function ProtectedFiles() {
  useDocumentTitle('Protected Files')
  const { show } = useToast()
  const { data: files, error, loading, reload, mutate } = useAsyncData((signal) => api.listFiles({ signal }))
  const [busyId, setBusyId] = useState<string | null>(null)

  const all = files ?? []
  // The list carries a pinned flag per file. If any file lacks it (null), the backend could not
  // report pin state, so we cannot tell pinned from unpinned - say so instead of showing "none".
  const backendReportsPins = all.every((f) => f.protected !== null)
  const pinned = useMemo(() => {
    const pinnedTime = (f: FileSummary) => Date.parse(f.pinnedAt ?? '') || 0
    return (files ?? [])
      .filter((f) => f.protected === true)
      .sort((a, b) => pinnedTime(b) - pinnedTime(a) || (a.filename ?? a.fileId).localeCompare(b.filename ?? b.fileId))
  }, [files])

  // Access history comes from the metadata endpoint, one request per pinned file (small, capped set).
  const pinnedIds = useMemo(() => pinned.map((f) => f.fileId), [pinned])
  const meta = useFileMetadata(pinnedIds)

  if (error) return <ErrorState error={error} onRetry={reload} />
  if (loading && !files) return <LoadingState rows={4} />

  async function unprotect(file: FileSummary) {
    setBusyId(file.fileId)
    try {
      await api.unprotectFile(file.fileId)
      mutate((current) => current.map((f) => (f.fileId === file.fileId ? { ...f, protected: false, pinnedAt: null } : f)))
      show('File unprotected.', 'success')
    } catch (err) {
      show(toUserMessage(err), 'error')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="flex items-center gap-2 text-2xl font-semibold text-slate-100">
          <ShieldCheck className="h-6 w-6 text-indigo-300" aria-hidden="true" />
          Protected Files
        </h2>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Files you pin in My Files are protected. Protected files remain observable by the ML system, but automated optimization respects the
          protection flag — they&apos;re excluded from automatic ML-driven tier changes. You can still move a protected file manually at any time.
        </p>
      </div>

      {!backendReportsPins ? (
        <CapabilityNotice capability="protectedFiles" title="The protected-files list is not available yet" className="items-center" />
      ) : pinned.length === 0 ? (
        <EmptyState
          icon={<ShieldCheck className="h-5 w-5" />}
          title="No protected files yet"
          description="Pin a file in My Files to protect it from automatic tiering. Pinning a Cold file also moves it back to Hot."
        />
      ) : (
        <ul className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {pinned.map((file) => {
            const name = file.filename ?? file.fileId
            const m = meta.get(file.fileId)
            const accessUnknown = !m || m.recentAccessCount === null
            return (
              <li key={file.fileId} className="flex flex-col gap-4 rounded-2xl border border-surface-border bg-surface-card/60 p-4 shadow-panel">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <FileTypeIcon filename={file.filename} />
                    <div className="min-w-0">
                      <p className="truncate font-medium text-slate-100" title={name}>{name}</p>
                      <p className="truncate text-xs text-slate-500">{fileKindLabel(file.filename)}</p>
                    </div>
                  </div>
                  <TierBadge tier={tierFromStorageClass(file.storageClass)} rawClass={file.storageClass} />
                </div>

                <dl className="space-y-1.5">
                  <Stat label="Size" value={formatBytes(file.size)} />
                  <Stat
                    label="Pinned"
                    value={file.pinnedAt ? formatRelativeShort(file.pinnedAt) : 'Before dates were recorded'}
                    muted={!file.pinnedAt}
                    title={file.pinnedAt ? formatDateTime(file.pinnedAt) : undefined}
                  />
                  <Stat
                    label="Last accessed"
                    value={!m ? '…' : accessUnknown ? 'Unavailable' : m.lastAccessedAt ? formatRelativeShort(m.lastAccessedAt) : 'Never'}
                    muted={!m || accessUnknown || !m.lastAccessedAt}
                    title={m?.lastAccessedAt ? formatDateTime(m.lastAccessedAt) : 'Counts downloads and shares'}
                  />
                  <Stat
                    label={`Accesses (${m?.accessWindowDays ?? 30}d)`}
                    value={!m ? '…' : accessUnknown ? 'Unavailable' : String(m.recentAccessCount)}
                    muted={!m || accessUnknown || m.recentAccessCount === 0}
                    title="Counts downloads and shares"
                  />
                </dl>

                <Button
                  variant="secondary"
                  size="sm"
                  className="w-full"
                  icon={<ShieldOff className="h-3.5 w-3.5" aria-hidden="true" />}
                  loading={busyId === file.fileId}
                  onClick={() => void unprotect(file)}
                >
                  Unprotect
                </Button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
