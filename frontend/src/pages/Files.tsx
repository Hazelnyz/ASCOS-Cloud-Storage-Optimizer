import { useMemo, useState } from 'react'
import { UploadCloud, Download, Share2, Trash2, FileIcon, Search, Eye, ArrowLeftRight, Pin, PinOff, ArrowUpDown, Filter } from 'lucide-react'
import { useAsyncData } from '@/hooks/useAsyncData'
import { useFileMetadata, invalidateMetadata, cacheMetadata } from '@/hooks/useFileMetadata'
import { api } from '@/services/api'
import { triggerDownload } from '@/lib/download'
import { toUserMessage } from '@/services/errors'
import { tierFromStorageClass, type FileSummary, type ShareLink, type StorageTier } from '@/types'
import { Button } from '@/components/common/Button'
import { Dropdown } from '@/components/common/Dropdown'
import { TierBadge } from '@/components/common/TierBadge'
import { EmptyState } from '@/components/common/EmptyState'
import { ErrorState } from '@/components/common/ErrorState'
import { LoadingState } from '@/components/common/LoadingState'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { UploadDialog } from '@/components/files/UploadDialog'
import { ShareDialog } from '@/components/files/ShareDialog'
import { TierChangeDialog } from '@/components/files/TierChangeDialog'
import { FileDetailsDialog } from '@/components/files/FileDetailsDialog'
import { SelectionActionBar } from '@/components/files/SelectionActionBar'
import { FileTypeIcon, fileKindLabel } from '@/components/files/FileTypeIcon'
import { useToast } from '@/context/toastContext'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { effectiveModified, formatBytes, formatDateTime, formatRelativeShort } from '@/lib/format'

const TIER_FILTERS: Array<StorageTier | 'ALL'> = ['ALL', 'HOT', 'WARM', 'COLD']

// Raw S3 StorageClass values (what the API/metadata cache actually store) -
// NOT the same as TIER_STORAGE_CLASS, which holds human-readable display
// labels ("S3 Standard-IA") for the tier dialogs. Mixing the two up silently
// breaks tierFromStorageClass() on the next read.
const TIER_TO_RAW_STORAGE_CLASS: Record<StorageTier, string> = {
  HOT: 'STANDARD',
  WARM: 'STANDARD_IA',
  COLD: 'GLACIER_IR',
}

type SortKey = 'name' | 'size' | 'modified'

export function FilesPage() {
  useDocumentTitle('My Files')
  const { show } = useToast()
  const { data: files, error, loading, reload, mutate } = useAsyncData((signal) => api.listFiles({ signal }))
  const [detailsFile, setDetailsFile] = useState<FileSummary | null>(null)
  const detailsId = detailsFile?.fileId ?? null
  // GET /files already returns each filename and storage class, so metadata is
  // only fetched for (a) files whose list-time name lookup failed and (b) the
  // file whose details are open (content type, upload time). This replaces the
  // old one-request-per-file hydration of the whole list.
  const ids = useMemo(() => {
    const need = (files ?? []).filter((f) => !f.filename).map((f) => f.fileId)
    if (detailsId && !need.includes(detailsId)) need.unshift(detailsId)
    return need
  }, [files, detailsId])
  const meta = useFileMetadata(ids)

  const [query, setQuery] = useState('')
  const [tierFilter, setTierFilter] = useState<StorageTier | 'ALL'>('ALL')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [pendingDelete, setPendingDelete] = useState<FileSummary[] | null>(null)
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [shareTarget, setShareTarget] = useState<{ file: FileSummary; link: ShareLink | null } | null>(null)
  const [rowBusy, setRowBusy] = useState<string | null>(null)
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' } | null>(null)
  const [tierChangeFile, setTierChangeFile] = useState<FileSummary | null>(null)
  const [protectBusyId, setProtectBusyId] = useState<string | null>(null)
  // Pinned state lives on the file list itself (GET /files reports `protected` and
  // `pinnedAt` per file), and pin/unpin responses are written back into that same
  // list - one source of truth for the badge, the menu label, the ordering and the
  // Protected Files page. It therefore survives reloads and is the same on every device.
  const pinnedIds = useMemo(() => new Set((files ?? []).filter((f) => f.protected === true).map((f) => f.fileId)), [files])
  const [pinConfirm, setPinConfirm] = useState<FileSummary[] | null>(null)
  const [bulkPinBusy, setBulkPinBusy] = useState(false)
  const [highlightId, setHighlightId] = useState<string | null>(null)

  function isProtected(fileId: string): boolean {
    return pinnedIds.has(fileId)
  }

  /** Writes a pin/unpin result into the list in place (no reload). */
  function applyPinResult(fileId: string, result: { protected: boolean; pinnedAt: string | null }) {
    mutate((current) =>
      current.map((f) =>
        f.fileId === fileId
          ? { ...f, protected: result.protected, pinnedAt: result.protected ? (result.pinnedAt ?? f.pinnedAt ?? new Date().toISOString()) : null }
          : f,
      ),
    )
  }

  function flash(fileId: string) {
    setHighlightId(fileId)
    window.setTimeout(() => setHighlightId((cur) => (cur === fileId ? null : cur)), 2500)
  }

  /** Pinning a Cold file moves it to Hot and can incur a retrieval charge, so confirm first (spec: Cold case only). */
  function requestToggleProtect(file: FileSummary) {
    if (!isProtected(file.fileId) && tierOf(file) === 'COLD') {
      setPinConfirm([file])
      return
    }
    void handleToggleProtect(file)
  }

  const unpinnedSelected = (files ?? []).filter((f) => selected.has(f.fileId) && !pinnedIds.has(f.fileId))

  function requestPinSelected() {
    if (unpinnedSelected.some((f) => tierOf(f) === 'COLD')) {
      setPinConfirm(unpinnedSelected)
      return
    }
    void pinMany(unpinnedSelected)
  }

  /** Bulk pin: a few requests at a time; reports one summary instead of one toast per file. */
  async function pinMany(targets: FileSummary[]) {
    if (targets.length === 0) return
    setBulkPinBusy(true)
    let pinned = 0
    let movedFromCold = 0
    for (let i = 0; i < targets.length; i += 5) {
      const chunk = targets.slice(i, i + 5)
      const results = await Promise.allSettled(chunk.map((f) => api.protectFile(f.fileId)))
      results.forEach((r, j) => {
        if (r.status !== 'fulfilled') return
        pinned += 1
        applyPinResult(chunk[j].fileId, r.value)
        if (r.value.tierChanged && r.value.newTier) {
          movedFromCold += 1
          applyTierToCaches(chunk[j].fileId, r.value.newTier)
        }
      })
    }
    const failed = targets.length - pinned
    setSelected(new Set())
    setBulkPinBusy(false)
    if (pinned > 0) {
      show(
        `${pinned} file${pinned === 1 ? '' : 's'} pinned${movedFromCold ? `, ${movedFromCold} moved from Cold to Hot` : ''}${failed ? `. ${failed} could not be pinned.` : '.'}`,
        failed ? 'info' : 'success',
      )
    } else {
      show('Could not pin the selected files. Please try again.', 'error')
    }
  }

  function tierOf(file: FileSummary): StorageTier | null {
    // The list row is the freshest source (it is re-fetched on refresh); cached metadata is only a fallback.
    return tierFromStorageClass(file.storageClass ?? meta.get(file.fileId)?.storageClass)
  }

  /** Real filename if known (list first, then metadata); null while unknown. */
  function nameOf(file: FileSummary): string | null {
    return file.filename ?? meta.get(file.fileId)?.filename ?? null
  }

  /** What to show for a file: its name, a loading hint, or (last resort) its id. */
  function labelOf(file: FileSummary): string {
    const name = nameOf(file)
    if (name) return name
    return !meta.get(file.fileId) && !meta.failed(file.fileId) ? 'Loading name…' : file.fileId
  }

  const allFiles = files ?? []
  const filtered = allFiles.filter((f) => {
    if (tierFilter !== 'ALL' && tierOf(f) !== tierFilter) return false
    if (!query.trim()) return true
    return (nameOf(f) ?? f.fileId).toLowerCase().includes(query.trim().toLowerCase())
  })
  // Pinned files always come first (that is what pinning is for). Inside each group:
  // a column the user clicked wins; otherwise pinned files are most-recently-pinned
  // first and everything else is A-Z by name.
  const pinnedTime = (f: FileSummary) => Date.parse(f.pinnedAt ?? '') || 0
  const byName = (a: FileSummary, b: FileSummary) => labelOf(a).toLowerCase().localeCompare(labelOf(b).toLowerCase())
  const sorted = [...filtered].sort((a, b) => {
    const pa = pinnedIds.has(a.fileId)
    const pb = pinnedIds.has(b.fileId)
    if (pa !== pb) return pa ? -1 : 1
    if (sort) {
      const m = sort.dir === 'asc' ? 1 : -1
      if (sort.key === 'size') return (a.size - b.size) * m
      if (sort.key === 'modified') return (Date.parse(effectiveModified(a)) - Date.parse(effectiveModified(b))) * m
      return byName(a, b) * m
    }
    if (pa) {
      const d = pinnedTime(b) - pinnedTime(a)
      if (d !== 0) return d
    }
    return byName(a, b)
  })
  const allSelected = filtered.length > 0 && filtered.every((f) => selected.has(f.fileId))
  const someSelected = filtered.some((f) => selected.has(f.fileId))

  function toggleSort(key: SortKey) {
    setSort((cur) => (cur?.key === key ? (cur.dir === 'asc' ? { key, dir: 'desc' } : null) : { key, dir: 'asc' }))
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  /** Reflects a tier change into both the list (size/lastModified stay put,
   * only the displayed tier moves) and the metadata cache, without a full
   * reload - same pattern as the existing delete/rename mutations below. */
  function applyTierToCaches(fileId: string, newTier: StorageTier) {
    const newClass = TIER_TO_RAW_STORAGE_CLASS[newTier]
    mutate((current) => current.map((f) => (f.fileId === fileId ? { ...f, storageClass: newClass } : f)))
    const existing = meta.get(fileId)
    if (existing) cacheMetadata({ ...existing, storageClass: newClass })
  }

  async function handleDownload(file: FileSummary) {
    setRowBusy(file.fileId)
    try {
      const { url } = await api.getDownloadLink(file.fileId)
      triggerDownload(url)
    } catch (err) {
      show(toUserMessage(err), 'error')
    } finally {
      setRowBusy(null)
    }
  }

  async function handleShare(file: FileSummary) {
    setShareTarget({ file, link: null })
    try {
      const link = await api.createShareLink(file.fileId)
      setShareTarget({ file, link })
    } catch (err) {
      setShareTarget(null)
      show(toUserMessage(err), 'error')
    }
  }

  async function handleToggleProtect(file: FileSummary) {
    const currentlyProtected = isProtected(file.fileId)
    setProtectBusyId(file.fileId)
    try {
      const result = currentlyProtected ? await api.unprotectFile(file.fileId) : await api.protectFile(file.fileId)
      applyPinResult(file.fileId, result)
      if (result.protected) flash(file.fileId)
      if (result.tierChanged && result.newTier) {
        applyTierToCaches(file.fileId, result.newTier)
        show(`Pinned, and moved from Cold to ${result.newTier}. It's at the top of your files.`, 'success')
      } else {
        show(result.protected ? 'Pinned. It now stays at the top of your files.' : 'File unpinned.', 'success')
      }
    } catch (err) {
      show(toUserMessage(err), 'error')
    } finally {
      setProtectBusyId(null)
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return
    setDeleteBusy(true)
    setDeleteError(null)
    const results = await Promise.allSettled(pendingDelete.map((f) => api.deleteFile(f.fileId)))
    const succeeded = pendingDelete.filter((_, i) => results[i].status === 'fulfilled')
    const failed = pendingDelete.filter((_, i) => results[i].status === 'rejected')

    // Drop everything that really was deleted from the list immediately, even if
    // other files in the same batch failed - otherwise they linger as stale rows
    // that would 404 on the next action.
    if (succeeded.length > 0) {
      const removedIds = new Set(succeeded.map((f) => f.fileId))
      succeeded.forEach((f) => invalidateMetadata(f.fileId))
      mutate((current) => current.filter((f) => !removedIds.has(f.fileId)))
      setSelected((prev) => { const next = new Set(prev); removedIds.forEach((id) => next.delete(id)); return next })
    }

    if (failed.length === 0) {
      show(succeeded.length === 1 ? 'File deleted.' : `${succeeded.length} files deleted.`, 'success')
      setPendingDelete(null)
    } else {
      if (succeeded.length > 0) show(`${succeeded.length} file${succeeded.length === 1 ? '' : 's'} deleted.`, 'success')
      // Keep the dialog open for only the files that still exist, so "retry" cannot re-delete the ones already gone.
      setPendingDelete(failed)
      setDeleteError(
        succeeded.length === 0
          ? toUserMessage((results.find((r) => r.status === 'rejected') as PromiseRejectedResult).reason)
          : `${failed.length} file${failed.length === 1 ? '' : 's'} could not be deleted. Try again for ${failed.length === 1 ? 'that one' : 'those'}.`,
      )
    }
    setDeleteBusy(false)
  }

  if (error) return <ErrorState error={error} onRetry={reload} />
  if (loading && !files) return <LoadingState rows={6} />

  const anySelected = selected.size > 0

  function sortHeader(k: SortKey, label: string, className = '') {
    const dir = sort?.key === k ? sort.dir : null
    return (
      <th key={k} scope="col" aria-sort={dir === 'asc' ? 'ascending' : dir === 'desc' ? 'descending' : 'none'} className={`px-4 py-3.5 font-medium ${className}`}>
        <button type="button" onClick={() => toggleSort(k)} className="focus-ring inline-flex items-center gap-1.5 rounded uppercase tracking-wide hover:text-slate-300">
          {label}
          <ArrowUpDown className={`h-3 w-3 ${dir ? 'text-indigo-300' : ''}`} aria-hidden="true" />
        </button>
      </th>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold text-slate-100">My Files</h2>
          <p className="mt-0.5 text-sm text-slate-500">{filtered.length} of {allFiles.length} file{allFiles.length === 1 ? '' : 's'}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="primary" className="px-5 py-2.5" icon={<UploadCloud className="h-4 w-4" />} onClick={() => setUploadOpen(true)}>Upload</Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[16rem] flex-1">
          <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" aria-hidden="true" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by filename…"
            aria-label="Search files by name"
            className="focus-ring w-full rounded-xl border border-surface-border bg-surface-raised py-3 pl-10 pr-3 text-sm text-slate-100 placeholder:text-slate-500"
          />
        </div>
        <div className="flex items-center gap-2" role="group" aria-label="Filter by tier">
          <Filter className="h-4 w-4 text-slate-500" aria-hidden="true" />
          {TIER_FILTERS.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTierFilter(t)}
              aria-pressed={tierFilter === t}
              className={`focus-ring rounded-lg border px-3.5 py-2 text-xs font-semibold tracking-wide transition-colors ${
                tierFilter === t ? 'border-accent bg-accent/10 text-indigo-300' : 'border-surface-border text-slate-300 hover:bg-white/5'
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>
      {meta.capped && <p className="text-[11px] text-slate-500">Search only covers the first {meta.cap} unnamed files while their names load.</p>}

      <SelectionActionBar
        count={selected.size}
        onClear={() => setSelected(new Set())}
        onDelete={() => setPendingDelete(allFiles.filter((f) => selected.has(f.fileId)))}
        onPin={unpinnedSelected.length > 0 ? requestPinSelected : undefined}
        pinBusy={bulkPinBusy}
      />

      {filtered.length === 0 ? (
        <EmptyState
          icon={<FileIcon className="h-5 w-5" />}
          title={allFiles.length > 0 ? 'No files match your filters' : 'No files yet'}
          description={allFiles.length > 0 ? 'Try a different name or tier.' : 'Upload a file to get started.'}
        />
      ) : (
        <div className="rounded-2xl border border-surface-border bg-surface-card/60 shadow-panel">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Your files</caption>
            <thead>
              <tr className="border-b border-surface-border text-xs uppercase tracking-wide text-slate-500">
                <th scope="col" aria-sort={sort?.key === 'name' ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'} className="px-4 py-3.5 font-medium">
                  <div className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      aria-label="Select all files"
                      className={`focus-ring accent-indigo-500 ${anySelected ? '' : 'opacity-40 hover:opacity-100'}`}
                      checked={allSelected}
                      ref={(el) => { if (el) el.indeterminate = someSelected && !allSelected }}
                      onChange={(e) => setSelected(e.target.checked ? new Set(filtered.map((f) => f.fileId)) : new Set())}
                    />
                    <button type="button" onClick={() => toggleSort('name')} className="focus-ring inline-flex items-center gap-1.5 rounded uppercase tracking-wide hover:text-slate-300">
                      File
                      <ArrowUpDown className={`h-3 w-3 ${sort?.key === 'name' ? 'text-indigo-300' : ''}`} aria-hidden="true" />
                    </button>
                  </div>
                </th>
                {sortHeader('size', 'Size')}
                {sortHeader('modified', 'Last Modified', 'hidden sm:table-cell')}
                <th scope="col" className="px-4 py-3.5 font-medium">Tier</th>
                <th scope="col" className="px-4 py-3.5 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-border/60">
              {sorted.map((file) => {
                const name = labelOf(file)
                const resolvedName = nameOf(file)
                const m = meta.get(file.fileId)
                const tier = tierOf(file)
                const protectedNow = isProtected(file.fileId)
                const isSelected = selected.has(file.fileId)
                return (
                  <tr
                    key={file.fileId}
                    className={`group transition-colors duration-700 ${highlightId === file.fileId ? 'bg-accent/15' : isSelected ? 'bg-accent/[0.06]' : 'hover:bg-white/[0.02]'}`}
                  >
                    <td className="max-w-[16rem] px-4 py-3.5 sm:max-w-md">
                      <div className="flex items-center gap-3.5">
                        <div className="relative shrink-0">
                          {/* Icon by default; the checkbox takes its place on hover/focus or once anything is selected. */}
                          <div className={anySelected ? 'invisible' : 'group-focus-within:invisible group-hover:invisible'}>
                            <FileTypeIcon filename={resolvedName} />
                          </div>
                          {protectedNow && (
                            <span
                              className="pointer-events-none absolute -right-1.5 -top-1.5 z-10 grid h-5 w-5 place-items-center rounded-full bg-accent text-white shadow ring-2 ring-surface-card"
                              title="Pinned"
                              aria-hidden="true"
                            >
                              <Pin className="h-3 w-3 rotate-45" />
                            </span>
                          )}
                          <label
                            className={`absolute inset-0 grid cursor-pointer place-items-center rounded-lg border border-surface-border bg-surface-raised ${
                              anySelected ? '' : 'opacity-0 focus-within:opacity-100 group-hover:opacity-100'
                            }`}
                          >
                            <input
                              type="checkbox"
                              aria-label={`Select ${name}`}
                              className="focus-ring accent-indigo-500"
                              checked={isSelected}
                              onChange={() => toggle(file.fileId)}
                            />
                          </label>
                        </div>
                        <div className="min-w-0">
                          <p className={`truncate font-medium ${resolvedName ? 'text-slate-100' : 'italic text-slate-400'}`} title={name}>{name}{protectedNow && <span className="sr-only"> (pinned)</span>}</p>
                          <p className="truncate text-xs text-slate-500">{fileKindLabel(resolvedName)}</p>
                        </div>
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3.5 tabular-nums text-slate-300">{formatBytes(file.size)}</td>
                    <td className="hidden whitespace-nowrap px-4 py-3.5 text-slate-300 sm:table-cell">
                      <time dateTime={effectiveModified(file)} title={formatDateTime(effectiveModified(file))}>{formatRelativeShort(effectiveModified(file))}</time>
                    </td>
                    <td className="px-4 py-3.5"><TierBadge tier={tier} rawClass={file.storageClass ?? m?.storageClass} /></td>
                    <td className="px-4 py-3.5 text-right">
                      <div className="inline-flex">
                        <Dropdown
                          label={`Actions for ${name}`}
                          items={[
                            { label: 'View details', icon: <Eye className="h-3.5 w-3.5" />, onSelect: () => setDetailsFile(file) },
                            { label: 'Download', icon: <Download className="h-3.5 w-3.5" />, disabled: rowBusy === file.fileId, onSelect: () => void handleDownload(file) },
                            { label: 'Share', icon: <Share2 className="h-3.5 w-3.5" />, disabled: rowBusy === file.fileId, onSelect: () => void handleShare(file) },
                            { label: 'Change tier', icon: <ArrowLeftRight className="h-3.5 w-3.5" />, onSelect: () => setTierChangeFile(file) },
                            {
                              label: protectedNow ? 'Unpin' : 'Pin',
                              icon: protectedNow ? <PinOff className="h-3.5 w-3.5 rotate-45" /> : <Pin className="h-3.5 w-3.5 rotate-45" />,
                              disabled: protectBusyId === file.fileId,
                              onSelect: () => requestToggleProtect(file),
                            },
                            { label: 'Delete', icon: <Trash2 className="h-3.5 w-3.5" />, danger: true, onSelect: () => setPendingDelete([file]) },
                          ]}
                        />
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} onUploaded={reload} />

      <ShareDialog
        open={shareTarget !== null}
        onClose={() => setShareTarget(null)}
        link={shareTarget?.link ?? null}
        filename={shareTarget ? labelOf(shareTarget.file) : ''}
      />

      <TierChangeDialog
        open={tierChangeFile !== null}
        onClose={() => setTierChangeFile(null)}
        filename={tierChangeFile ? labelOf(tierChangeFile) : ''}
        currentTier={tierChangeFile ? tierOf(tierChangeFile) : null}
        protectedHint={tierChangeFile ? isProtected(tierChangeFile.fileId) : false}
        onSubmit={(target) => api.changeTier((tierChangeFile as FileSummary).fileId, target)}
        onChanged={(result) => {
          applyTierToCaches(result.fileId, result.newTier)
          mutate((current) => current.map((f) => (f.fileId === result.fileId ? { ...f, protected: result.protected } : f)))
          show(result.status === 'no_action_needed' ? 'Already at that tier - no action needed.' : `Moved to ${result.newTier}.`, 'success')
        }}
      />

      <FileDetailsDialog
        open={detailsFile !== null}
        onClose={() => setDetailsFile(null)}
        filename={detailsFile ? labelOf(detailsFile) : ''}
        metadata={detailsFile ? (meta.get(detailsFile.fileId) ?? null) : null}
        metadataError={detailsFile && meta.failed(detailsFile.fileId) ? 'Could not load file details.' : null}
        isProtected={detailsFile ? isProtected(detailsFile.fileId) : false}
        protectBusy={detailsFile ? protectBusyId === detailsFile.fileId : false}
        onToggleProtect={() => detailsFile && requestToggleProtect(detailsFile)}
      />

      <ConfirmDialog
        open={pinConfirm !== null}
        title={pinConfirm && pinConfirm.length > 1 ? 'Pin files from Cold?' : 'Pin a Cold file?'}
        confirmLabel="Pin and move to Hot"
        confirmVariant="primary"
        onCancel={() => setPinConfirm(null)}
        onConfirm={() => {
          const targets = pinConfirm
          setPinConfirm(null)
          if (!targets) return
          if (targets.length === 1) void handleToggleProtect(targets[0])
          else void pinMany(targets)
        }}
      >
        {pinConfirm && pinConfirm.length === 1 && (
          <p>
            <span className="font-medium text-slate-200">{labelOf(pinConfirm[0])}</span> is in Cold storage. Pinning it moves it to Hot right away,
            which can include a small retrieval charge. Pinned files are not moved automatically afterwards.
          </p>
        )}
        {pinConfirm && pinConfirm.length > 1 && (
          <p>
            {pinConfirm.filter((f) => tierOf(f) === 'COLD').length} of these {pinConfirm.length} files are in Cold storage. Pinning moves them to Hot
            right away, which can include a small retrieval charge. Pinned files are not moved automatically afterwards.
          </p>
        )}
      </ConfirmDialog>

      <ConfirmDialog
        open={pendingDelete !== null}
        title={pendingDelete && pendingDelete.length > 1 ? `Delete ${pendingDelete.length} files?` : 'Delete file?'}
        confirmLabel="Delete"
        busy={deleteBusy}
        error={deleteError}
        onCancel={() => { setPendingDelete(null); setDeleteError(null) }}
        onConfirm={() => void confirmDelete()}
      >
        {pendingDelete && pendingDelete.length === 1 ? (
          <p>
            <span className="font-medium text-slate-200">{labelOf(pendingDelete[0])}</span> will be permanently deleted. This cannot be undone.
          </p>
        ) : (
          <p>{pendingDelete?.length} files will be permanently deleted. This cannot be undone.</p>
        )}
      </ConfirmDialog>
    </div>
  )
}
