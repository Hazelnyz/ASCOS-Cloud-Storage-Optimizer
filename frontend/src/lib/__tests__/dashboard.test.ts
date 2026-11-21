import { describe, expect, it } from 'vitest'
import type { FileSummary, Prediction } from '@/types'
import { countHighAccess, formatDashboardRelativeTime, getTierStats, optimizationCandidates, recentRecommendations } from '../dashboard'

const file = (fileId: string, storageClass: string | null, protectedState: boolean | null = false, modified = '2026-01-01T00:00:00Z'): FileSummary => ({
  fileId, filename: `${fileId}.txt`, size: 100, lastModified: modified, storageClass, uploadedAt: null, protected: protectedState, pinnedAt: null,
})
const prediction = (fileId: string, pAccess: number | null, candidateTiers: Prediction['candidateTiers'], timestamp: string | null): Prediction => ({
  fileId, pAccess, candidateTiers, banditChoice: null, predictionTimestamp: timestamp, topReasons: null,
})

describe('dashboard helpers', () => {
  it('counts files, bytes and percentages by tier, with percentages rounded to one decimal', () => {
    const stats = getTierStats([file('a', 'STANDARD'), file('b', 'STANDARD'), file('c', 'STANDARD_IA'), file('d', null)])
    expect(stats.HOT).toEqual({ count: 2, bytes: 200, percent: 50 })
    expect(stats.WARM).toEqual({ count: 1, bytes: 100, percent: 25 })
    expect(stats.COLD).toEqual({ count: 0, bytes: 0, percent: 0 })
  })

  it('counts high access at the 0.7 threshold and deduplicates files', () => {
    expect(countHighAccess([prediction('a', 0.6999, [], '2026-01-01'), prediction('b', 0.7, [], '2026-01-01'), prediction('b', 0.8, [], '2026-01-02')])).toBe(1)
  })

  it('excludes pinned, same-tier, missing-file and missing predictions from candidates', () => {
    const files = [file('a', 'STANDARD'), file('b', 'STANDARD', true), file('c', 'STANDARD')]
    expect(optimizationCandidates([
      prediction('a', 0.5, ['WARM'], '2026-01-01'), prediction('b', 0.5, ['COLD'], '2026-01-01'),
      prediction('c', 0.5, ['HOT'], '2026-01-01'), prediction('absent', 0.5, ['COLD'], '2026-01-01'),
    ], files).map((row) => row.fileId)).toEqual(['a'])
  })

  it('orders latest recommendations newest first and joins filenames', () => {
    const rows = recentRecommendations([
      prediction('a', 0.2, [], '2026-01-01T00:00:00Z'), prediction('b', 0.7, ['COLD'], '2026-01-03T00:00:00Z'),
      prediction('a', 0.6, ['WARM'], '2026-01-02T00:00:00Z'),
    ], [file('a', 'STANDARD')])
    expect(rows.map(({ prediction: row, file: joined }) => [row.fileId, joined?.filename ?? null])).toEqual([['b', null], ['a', 'a.txt']])
  })

  it('formats relative time with correct singular and plural forms', () => {
    const now = Date.parse('2026-10-27T12:00:00Z')
    expect(formatDashboardRelativeTime('2026-10-27T11:59:30Z', now)).toBe('just now')
    expect(formatDashboardRelativeTime('2026-10-27T11:00:00Z', now)).toBe('1 hour ago')
    expect(formatDashboardRelativeTime('2026-10-26T12:00:00Z', now)).toBe('1 day ago')
    expect(formatDashboardRelativeTime('2026-09-27T12:00:00Z', now)).toBe('1 month ago')
    expect(formatDashboardRelativeTime('2026-08-27T12:00:00Z', now)).toBe('2 months ago')
  })
})
