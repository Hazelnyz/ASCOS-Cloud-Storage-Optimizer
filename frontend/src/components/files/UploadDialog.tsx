import { useRef, useState } from 'react'
import { UploadCloud, X, CheckCircle2, XCircle, RotateCcw } from 'lucide-react'
import { Modal } from '@/components/common/Modal'
import { Button } from '@/components/common/Button'
import { api } from '@/services/api'
import { uploadFile, MAX_SINGLE_PUT_BYTES } from '@/services/upload'
import { toUserMessage } from '@/services/errors'
import { formatBytes } from '@/lib/format'

type ItemStatus = 'queued' | 'uploading' | 'done' | 'error'
interface QueueItem { id: string; file: File; status: ItemStatus; progress: number; error?: string }

function newId() {
  return typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`
}

export function UploadDialog({ open, onClose, onUploaded }: { open: boolean; onClose: () => void; onUploaded: () => void }) {
  const [items, setItems] = useState<QueueItem[]>([])
  const inputRef = useRef<HTMLInputElement>(null)
  const controllersRef = useRef(new Map<string, AbortController>())
  const anyDone = items.some((i) => i.status === 'done')
  const anyBusy = items.some((i) => i.status === 'uploading' || i.status === 'queued')

  function addFiles(files: FileList | null) {
    if (!files) return
    const next: QueueItem[] = Array.from(files).map((file) => ({ id: newId(), file, status: 'queued', progress: 0 }))
    setItems((prev) => [...prev, ...next])
    next.forEach(start)
  }

  function start(item: QueueItem) {
    const controller = new AbortController()
    controllersRef.current.set(item.id, controller)
    setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, status: 'uploading', progress: 0, error: undefined } : i)))
    uploadFile(api, item.file, {
      signal: controller.signal,
      onProgress: (fraction) => setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, progress: fraction } : i))),
    })
      .then(() => setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, status: 'done', progress: 1 } : i))))
      .catch((err) => setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, status: 'error', error: toUserMessage(err) } : i))))
      .finally(() => controllersRef.current.delete(item.id))
  }

  function retry(item: QueueItem) {
    start(item) // a retry always requests a fresh upload URL (upload.ts)
  }

  function remove(id: string) {
    controllersRef.current.get(id)?.abort()
    setItems((prev) => prev.filter((i) => i.id !== id))
  }

  function handleClose() {
    if (anyBusy) return
    items.forEach((i) => controllersRef.current.get(i.id)?.abort())
    setItems([])
    onClose()
    if (anyDone) onUploaded()
  }

  return (
    <Modal open={open} onClose={handleClose} title="Upload files" size="lg" dismissible={!anyBusy}>
      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); addFiles(e.dataTransfer.files) }}
        className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-surface-border p-6 text-center"
      >
        <UploadCloud className="h-6 w-6 text-slate-400" aria-hidden="true" />
        <p className="text-sm text-slate-300">Drag files here, or</p>
        <Button variant="secondary" size="sm" onClick={() => inputRef.current?.click()}>Choose files</Button>
        <p className="text-xs text-slate-500">Up to {formatBytes(MAX_SINGLE_PUT_BYTES)} per file.</p>
        <input ref={inputRef} type="file" multiple className="hidden" onChange={(e) => { addFiles(e.target.files); e.target.value = '' }} />
      </div>

      {items.length > 0 && (
        <ul className="mt-4 max-h-64 space-y-2 overflow-y-auto">
          {items.map((item) => (
            <li key={item.id} className="rounded-lg border border-surface-border bg-surface-raised p-2.5">
              <div className="flex items-center justify-between gap-2">
                <p className="min-w-0 flex-1 truncate text-xs text-slate-200">{item.file.name}</p>
                {item.status === 'done' && <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" aria-hidden="true" />}
                {item.status === 'error' && <XCircle className="h-4 w-4 shrink-0 text-rose-400" aria-hidden="true" />}
                {item.status === 'error' && (
                  <button onClick={() => retry(item)} className="focus-ring rounded p-0.5 text-slate-400 hover:text-slate-200" aria-label={`Retry ${item.file.name}`}>
                    <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                )}
                {item.status !== 'uploading' && (
                  <button onClick={() => remove(item.id)} className="focus-ring rounded p-0.5 text-slate-400 hover:text-slate-200" aria-label={`Remove ${item.file.name}`}>
                    <X className="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                )}
              </div>
              {item.status === 'uploading' && (
                <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-white/5">
                  <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${Math.round(item.progress * 100)}%` }} />
                </div>
              )}
              {item.status === 'error' && <p className="mt-1 text-[11px] text-rose-400">{item.error}</p>}
            </li>
          ))}
        </ul>
      )}
      <div className="mt-4 flex justify-end">
        <Button variant="secondary" onClick={handleClose} disabled={anyBusy}>{anyBusy ? 'Uploading…' : 'Done'}</Button>
      </div>
    </Modal>
  )
}
