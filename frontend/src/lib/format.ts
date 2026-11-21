export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)))
  const value = bytes / 1024 ** i
  return `${value >= 100 ? value.toFixed(0) : value.toFixed(1)} ${units[i]}`
}

export function formatUsd(amount: number): string {
  return amount.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

export function formatPercent(value: number, digits = 1): string {
  return `${value.toFixed(digits)}%`
}

export function formatRelativeDate(iso: string | null): string {
  if (!iso) return 'Never accessed'
  const then = new Date(iso).getTime()
  const now = Date.now()
  const diffMs = now - then
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))
  if (diffDays <= 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 30) return `${diffDays} days ago`
  if (diffDays < 365) return `${Math.floor(diffDays / 30)} months ago`
  return `${Math.floor(diffDays / 365)} years ago`
}

export function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
}

export function formatPAccess(p: number | null): string {
  if (p === null) return '—'
  return `${Math.round(p * 100)}%`
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}

export function formatDuration(seconds: number): string {
  if (seconds % 86_400 === 0) {
    const d = seconds / 86_400
    return `${d} day${d === 1 ? '' : 's'}`
  }
  if (seconds % 3_600 === 0) {
    const h = seconds / 3_600
    return `${h} hour${h === 1 ? '' : 's'}`
  }
  const m = Math.max(1, Math.round(seconds / 60))
  return `${m} minute${m === 1 ? '' : 's'}`
}

/** Compact relative time for table cells ("5 min ago", "3 d ago"); falls back to a date past 30 days. */
export function formatRelativeShort(iso: string | null, now: number = Date.now()): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const sec = Math.max(0, Math.floor((now - then) / 1000))
  if (sec < 60) return 'Just now'
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min} min ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} h ago`
  const day = Math.floor(hr / 24)
  if (day < 30) return `${day} d ago`
  return formatDate(iso)
}

/**
 * The date to show as a file's "last modified". Files are never edited in
 * place, but S3's LastModified is reset by every tier change or pin, so the
 * server-recorded upload time wins when the object has one.
 */
export function effectiveModified(file: { uploadedAt?: string | null; lastModified: string }): string {
  return file.uploadedAt || file.lastModified
}
