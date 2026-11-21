import { dedupePredictions } from '@/lib/predictions'
import { effectiveModified } from '@/lib/format'
import { tierFromStorageClass, type FileSummary, type Prediction, type StorageTier } from '@/types'

export const DASHBOARD_TIERS: StorageTier[] = ['HOT', 'WARM', 'COLD']

export function getTierStats(files: FileSummary[]) {
  const counts: Record<StorageTier, { count: number; bytes: number; percent: number }> = {
    HOT: { count: 0, bytes: 0, percent: 0 }, WARM: { count: 0, bytes: 0, percent: 0 }, COLD: { count: 0, bytes: 0, percent: 0 },
  }
  for (const file of files) {
    const tier = tierFromStorageClass(file.storageClass)
    if (tier) { counts[tier].count++; counts[tier].bytes += file.size }
  }
  for (const tier of DASHBOARD_TIERS) counts[tier].percent = files.length ? Number((counts[tier].count / files.length * 100).toFixed(1)) : 0
  return counts
}

export function countHighAccess(predictions: Prediction[]): number {
  return dedupePredictions(predictions).filter((row) => row.pAccess !== null && row.pAccess >= 0.7).length
}

export function optimizationCandidates(predictions: Prediction[], files: FileSummary[]): Prediction[] {
  const fileMap = new Map(files.map((file) => [file.fileId, file]))
  return dedupePredictions(predictions).filter((row) => {
    if (!row.fileId) return false
    const file = fileMap.get(row.fileId)
    const currentTier = file && tierFromStorageClass(file.storageClass)
    return Boolean(file && file.protected !== true && currentTier && row.candidateTiers.some((tier) => tier !== currentTier))
  })
}

export function recentRecommendations(predictions: Prediction[], files: FileSummary[]) {
  const fileMap = new Map(files.map((file) => [file.fileId, file]))
  return dedupePredictions(predictions)
    .sort((a, b) => (Date.parse(b.predictionTimestamp ?? '') || 0) - (Date.parse(a.predictionTimestamp ?? '') || 0))
    .map((prediction) => ({ prediction, file: fileMap.get(prediction.fileId ?? '') ?? null }))
}

export function recentFiles(files: FileSummary[]) {
  return [...files].sort((a, b) => (Date.parse(effectiveModified(b)) || 0) - (Date.parse(effectiveModified(a)) || 0))
}

export function formatDashboardRelativeTime(iso: string | null, now = Date.now()): string {
  if (!iso) return '—'
  const timestamp = Date.parse(iso)
  if (!Number.isFinite(timestamp)) return '—'
  const seconds = Math.max(0, Math.floor((now - timestamp) / 1000))
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} day${days === 1 ? '' : 's'} ago`
  const months = Math.floor(days / 30)
  if (months < 12) return `${months} month${months === 1 ? '' : 's'} ago`
  const years = Math.floor(days / 365)
  return `${years} year${years === 1 ? '' : 's'} ago`
}
