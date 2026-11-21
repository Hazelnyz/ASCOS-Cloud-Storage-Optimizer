import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { Modal } from '@/components/common/Modal'
import { Button } from '@/components/common/Button'
import { formatDateTime, formatDuration } from '@/lib/format'
import type { ShareLink } from '@/types'

export function ShareDialog({ open, onClose, link, filename }: { open: boolean; onClose: () => void; link: ShareLink | null; filename: string }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    if (!link) return
    try {
      await navigator.clipboard.writeText(link.url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard access can be denied by the browser; the link is still selectable text.
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={`Share "${filename}"`}>
      {link ? (
        <div className="space-y-3">
          <div className="flex items-center gap-2 rounded-lg border border-surface-border bg-surface-raised p-2">
            <input readOnly value={link.url} className="min-w-0 flex-1 truncate bg-transparent text-xs text-slate-200 outline-none" onFocus={(e) => e.currentTarget.select()} />
            <Button variant="secondary" size="sm" icon={copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />} onClick={copy}>
              {copied ? 'Copied' : 'Copy'}
            </Button>
          </div>
          <p className="text-xs text-slate-400">
            {link.expiresAt
              ? <>Expires {formatDateTime(link.expiresAt)}.</>
              : link.expiresInSeconds
                ? <>Valid for {formatDuration(link.expiresInSeconds)} from now.</>
                : <>This backend version does not report a link expiry — treat it as short-lived.</>}
            {' '}This link cannot be revoked before it expires. Anyone with the link can view the file.
          </p>
        </div>
      ) : (
        <p className="text-sm text-slate-400">Generating link…</p>
      )}
    </Modal>
  )
}
