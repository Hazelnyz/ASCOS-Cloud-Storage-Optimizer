import { describe, it, expect } from 'vitest'
import { dedupePredictions, bandOf, countByBand } from '../predictions'
import type { Prediction } from '@/types'

describe('dedupePredictions', () => {
  it('keeps newest prediction per file_id', () => {
    const rows: Prediction[] = [
      { fileId: 'file1', pAccess: 0.5, candidateTiers: [], banditChoice: null, predictionTimestamp: '2026-01-01T10:00:00Z', topReasons: null },
      { fileId: 'file1', pAccess: 0.7, candidateTiers: [], banditChoice: null, predictionTimestamp: '2026-01-02T10:00:00Z', topReasons: null },
      { fileId: 'file2', pAccess: 0.3, candidateTiers: [], banditChoice: null, predictionTimestamp: '2026-01-01T10:00:00Z', topReasons: null },
    ]
    const result = dedupePredictions(rows)
    expect(result).toHaveLength(2)
    expect(result.find(r => r.fileId === 'file1')?.pAccess).toBe(0.7)
    expect(result.find(r => r.fileId === 'file2')?.pAccess).toBe(0.3)
  })

  it('handles rows without fileId', () => {
    const rows: Prediction[] = [
      { fileId: null, pAccess: 0.5, candidateTiers: [], banditChoice: null, predictionTimestamp: '2026-01-01T10:00:00Z', topReasons: null },
      { fileId: 'file1', pAccess: 0.7, candidateTiers: [], banditChoice: null, predictionTimestamp: '2026-01-01T10:00:00Z', topReasons: null },
    ]
    const result = dedupePredictions(rows)
    expect(result).toHaveLength(1)
    expect(result[0].fileId).toBe('file1')
  })

  it('handles empty array', () => {
    expect(dedupePredictions([])).toEqual([])
  })
})

describe('bandOf', () => {
  it('returns high for p_access >= 0.7', () => {
    expect(bandOf(0.7)).toBe('high')
    expect(bandOf(0.8)).toBe('high')
    expect(bandOf(1.0)).toBe('high')
  })

  it('returns medium for 0.3 <= p_access < 0.7', () => {
    expect(bandOf(0.3)).toBe('medium')
    expect(bandOf(0.5)).toBe('medium')
    expect(bandOf(0.69)).toBe('medium')
  })

  it('returns low for p_access < 0.3', () => {
    expect(bandOf(0)).toBe('low')
    expect(bandOf(0.1)).toBe('low')
    expect(bandOf(0.29)).toBe('low')
  })

  it('returns null for null p_access', () => {
    expect(bandOf(null)).toBeNull()
  })
})

describe('countByBand', () => {
  it('counts predictions by band correctly', () => {
    const rows: Prediction[] = [
      { fileId: 'f1', pAccess: 0.8, candidateTiers: [], banditChoice: null, predictionTimestamp: '2026-01-01T10:00:00Z', topReasons: null },
      { fileId: 'f2', pAccess: 0.5, candidateTiers: [], banditChoice: null, predictionTimestamp: '2026-01-01T10:00:00Z', topReasons: null },
      { fileId: 'f3', pAccess: 0.2, candidateTiers: [], banditChoice: null, predictionTimestamp: '2026-01-01T10:00:00Z', topReasons: null },
      { fileId: 'f4', pAccess: 0.7, candidateTiers: [], banditChoice: null, predictionTimestamp: '2026-01-01T10:00:00Z', topReasons: null },
      { fileId: 'f5', pAccess: 0.3, candidateTiers: [], banditChoice: null, predictionTimestamp: '2026-01-01T10:00:00Z', topReasons: null },
    ]
    const result = countByBand(rows)
    expect(result.high).toBe(2) // 0.8, 0.7
    expect(result.medium).toBe(2) // 0.5, 0.3
    expect(result.low).toBe(1) // 0.2
  })

  it('counts add up to total files', () => {
    const rows: Prediction[] = [
      { fileId: 'f1', pAccess: 0.5, candidateTiers: [], banditChoice: null, predictionTimestamp: '2026-01-01T10:00:00Z', topReasons: null },
      { fileId: 'f2', pAccess: 0.2, candidateTiers: [], banditChoice: null, predictionTimestamp: '2026-01-01T10:00:00Z', topReasons: null },
      { fileId: 'f3', pAccess: null, candidateTiers: [], banditChoice: null, predictionTimestamp: '2026-01-01T10:00:00Z', topReasons: null },
    ]
    const result = countByBand(rows)
    expect(result.high + result.medium + result.low).toBe(2) // null excluded
  })
})
