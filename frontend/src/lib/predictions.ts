import type { Prediction } from '@/types'

export type Band = 'high' | 'medium' | 'low'

/**
 * Deduplicate prediction rows by file_id, keeping the newest prediction_timestamp.
 */
export function dedupePredictions(rows: Prediction[]): Prediction[] {
  const map = new Map<string, Prediction>()
  
  for (const row of rows) {
    if (!row.fileId) continue
    const existing = map.get(row.fileId)
    if (!existing || (row.predictionTimestamp && existing.predictionTimestamp && row.predictionTimestamp > existing.predictionTimestamp)) {
      map.set(row.fileId, row)
    }
  }
  
  return Array.from(map.values())
}

/**
 * Determine the probability band for a p_access value.
 * - high: p_access >= 0.7
 * - medium: 0.3 <= p_access < 0.7
 * - low: p_access < 0.3
 */
export function bandOf(pAccess: number | null): Band | null {
  if (pAccess === null) return null
  if (pAccess >= 0.7) return 'high'
  if (pAccess >= 0.3) return 'medium'
  return 'low'
}

/**
 * Count predictions by band.
 */
export function countByBand(rows: Prediction[]): { high: number; medium: number; low: number } {
  let high = 0
  let medium = 0
  let low = 0
  
  for (const row of rows) {
    const band = bandOf(row.pAccess)
    if (band === 'high') high++
    else if (band === 'medium') medium++
    else if (band === 'low') low++
  }
  
  return { high, medium, low }
}
