import { describe, it, expect } from 'vitest'
import { adaptAnalyticsSummary, adaptBudgetUpdate, adaptCostSummary, adaptFileList, adaptMetadata, adaptUploadTicket, adaptPredictions, adaptDeleteResult, adaptProtectResult, adaptStoragePreferences } from '../adapters'
import { ApiError } from '../errors'

describe('adaptFileList', () => {
  it('maps the GET /files shape, with filename and storageClass absent', () => {
    const files = adaptFileList({ files: [{ fileId: 'a', size: 10, lastModified: '2026-01-01T00:00:00Z' }] })
    expect(files).toEqual([{ fileId: 'a', filename: null, size: 10, lastModified: '2026-01-01T00:00:00Z', storageClass: null, uploadedAt: null, protected: null, pinnedAt: null }])
  })

  it('keeps the filename and storageClass the list endpoint returns', () => {
    const files = adaptFileList({
      files: [{ fileId: 'a', filename: 'report.pdf', size: 10, lastModified: '2026-01-01T00:00:00Z', storageClass: 'STANDARD_IA' }],
    })
    expect(files[0].filename).toBe('report.pdf')
    expect(files[0].storageClass).toBe('STANDARD_IA')
  })

  it('reads the pinned state when the list endpoint reports it, and leaves it null when absent', () => {
    const files = adaptFileList({
      files: [
        { fileId: 'a', size: 1, lastModified: '2026-01-01T00:00:00Z', protected: true },
        { fileId: 'b', size: 1, lastModified: '2026-01-01T00:00:00Z' },
      ],
    })
    expect(files[0].protected).toBe(true)
    expect(files[1].protected).toBeNull()
  })

  it('reads pinnedAt, and keeps explicit false distinct from unknown', () => {
    const files = adaptFileList({
      files: [
        { fileId: 'a', size: 1, lastModified: '2026-01-01T00:00:00Z', protected: true, pinnedAt: '2026-10-04T00:00:00+00:00' },
        { fileId: 'b', size: 1, lastModified: '2026-01-01T00:00:00Z', protected: false, pinnedAt: null },
      ],
    })
    expect(files[0].pinnedAt).toBe('2026-10-04T00:00:00+00:00')
    expect(files[1].protected).toBe(false)
    expect(files[1].pinnedAt).toBeNull()
  })

  it('reads uploadedAt when present', () => {
    const files = adaptFileList({ files: [{ fileId: 'a', size: 1, lastModified: '2026-01-02T00:00:00Z', uploadedAt: '2026-01-01T00:00:00+00:00' }] })
    expect(files[0].uploadedAt).toBe('2026-01-01T00:00:00+00:00')
  })

  it('treats a null filename (per-object HeadObject failure) as unknown, not as an error', () => {
    const files = adaptFileList({ files: [{ fileId: 'a', filename: null, size: 1, lastModified: '2026-01-01T00:00:00Z' }] })
    expect(files[0].filename).toBeNull()
  })

  it('throws ApiError(malformed) rather than returning undefined fields on a shape mismatch', () => {
    expect(() => adaptFileList({ files: [{ size: 10 }] })).toThrow(ApiError)
  })
})

describe('adaptStoragePreferences', () => {
  it('accepts a real boolean setting', () => {
    expect(adaptStoragePreferences({ auto_tier_enabled: false })).toEqual({ auto_tier_enabled: false })
  })

  it('rejects non-boolean setting values', () => {
    expect(() => adaptStoragePreferences({ auto_tier_enabled: 'false' })).toThrow(ApiError)
  })
})

describe('adaptMetadata', () => {
  it('defaults storageClass to STANDARD when absent, matching the handler', () => {
    const meta = adaptMetadata({ fileId: 'a', size: 1, lastModified: null, contentType: null, filename: null })
    expect(meta.storageClass).toBe('STANDARD')
  })

  it('preserves a null filename rather than inventing one', () => {
    const meta = adaptMetadata({ fileId: 'a', size: 1, filename: null })
    expect(meta.filename).toBeNull()
  })

  it('reads access history, and keeps "0 accesses" distinct from "unknown"', () => {
    const known = adaptMetadata({ fileId: 'a', size: 1, lastAccessedAt: '2026-10-01T00:00:00Z', recentAccessCount: 3, accessWindowDays: 30 })
    expect(known.lastAccessedAt).toBe('2026-10-01T00:00:00Z')
    expect(known.recentAccessCount).toBe(3)
    const never = adaptMetadata({ fileId: 'a', size: 1, lastAccessedAt: null, recentAccessCount: 0, accessWindowDays: 30 })
    expect(never.recentAccessCount).toBe(0)
    const unknown = adaptMetadata({ fileId: 'a', size: 1, lastAccessedAt: null, recentAccessCount: null })
    expect(unknown.recentAccessCount).toBeNull()
    expect(adaptMetadata({ fileId: 'a', size: 1 }).recentAccessCount).toBeNull()
  })
})

describe('adaptUploadTicket', () => {
  it('accepts a ticket with no headers field (pre-Unicode-fix backend)', () => {
    const ticket = adaptUploadTicket({ fileId: 'a', uploadUrl: 'https://s3.example/x' })
    expect(ticket.headers).toBeNull()
  })

  it('maps signed headers when the backend provides them', () => {
    const ticket = adaptUploadTicket({ fileId: 'a', uploadUrl: 'https://s3.example/x', headers: { 'x-amz-meta-filename': 'a%2Epdf' } })
    expect(ticket.headers).toEqual({ 'x-amz-meta-filename': 'a%2Epdf' })
  })
})

describe('adaptPredictions', () => {
  it('drops an unrecognised tier value rather than passing it through', () => {
    const preds = adaptPredictions({ predictions: [{ fileId: 'a', pAccess: 0.5, candidateTiers: ['HOT', 'FROZEN'], banditChoice: null, predictionTimestamp: null }] })
    expect(preds[0].candidateTiers).toEqual(['HOT'])
  })

  it('handles an empty prediction set (expected today - prediction-fn is a scaffold)', () => {
    expect(adaptPredictions({ predictions: [] })).toEqual([])
  })
})

describe('adaptAnalyticsSummary', () => {
  it('maps aggregated analytics and preserves a null optimization', () => {
    expect(adaptAnalyticsSummary({
      tiers: [{ tier: 'HOT', files: 2, bytes: 2048 }],
      types: [{ type: 'pdf', files: 2 }],
      storageOverTime: [{ day: '2026-10-23', bytes: 2048 }],
      access: [{ day: '2026-10-23', reads: 1, writes: 2, downloads: 3 }],
      optimization: null,
    })).toEqual({
      tiers: [{ tier: 'HOT', files: 2, bytes: 2048 }],
      types: [{ type: 'pdf', files: 2 }],
      storageOverTime: [{ day: '2026-10-23', bytes: 2048 }],
      access: [{ day: '2026-10-23', reads: 1, writes: 2, downloads: 3 }],
      optimization: null,
    })
  })

  it('rejects malformed analytics rows instead of rendering fabricated values', () => {
    expect(() => adaptAnalyticsSummary({ tiers: [], types: [], storageOverTime: [], access: [{ day: 'today' }] })).toThrow(ApiError)
  })
})

describe('cost adapters', () => {
  it('maps the per-user estimate and preserves unavailable shared overhead', () => {
    const result = adaptCostSummary({
      budget: 100, alert_threshold: 80, estimated_spent: 12.5,
      breakdown: [{ category: 'Shared overhead', amount: null }],
      storage_by_tier: {
        HOT: { bytes: 1, gb: 1 / 1024 ** 3, rate: 0.025, cost: 0.000000025 },
        WARM: { bytes: 0, gb: 0, rate: 0.0138, cost: 0 }, COLD: { bytes: 0, gb: 0, rate: 0.005, cost: 0 },
      },
      rates_used: {
        storage: { HOT: 0.025, WARM: 0.0138, COLD: 0.005 },
        requests: { standard_write: 0.005, standard_read: 0.0004, warm_write: 0.01, warm_read: 0.001, cold_write: 0.02, cold_read: 0.01, delete: 0 },
        retrieval: { warm: 0.01, cold: 0.03 }, notes: 'approximate rates',
      },
      computed_at: '2026-10-28T00:00:00Z', ml_savings_estimate: null,
      budget_config: { min: 0, max: 500, step: 5, alert_threshold_min: 1, alert_threshold_max: 100 },
    })
    expect(result.budget).toBe(100)
    expect(result.breakdown[0].amount).toBeNull()
    expect(result.rates_used.notes).toContain('approximate')
    expect(result.ml_savings_estimate).toBeNull()
  })

  it('maps the server-confirmed budget update response', () => {
    expect(adaptBudgetUpdate({ budget: 150, alert_threshold: 75 })).toEqual({ budget: 150, alert_threshold: 75 })
  })
})

describe('adaptDeleteResult', () => {
  it('accepts {deleted: true}', () => {
    expect(() => adaptDeleteResult({ fileId: 'a', deleted: true })).not.toThrow()
  })
  it('rejects a response without deleted:true', () => {
    expect(() => adaptDeleteResult({ fileId: 'a' })).toThrow(ApiError)
  })
})

describe('adaptProtectResult', () => {
  it('accepts a lower- or upper-case newTier from the backend', () => {
    expect(adaptProtectResult({ fileId: 'a', protected: true, tierChanged: true, newTier: 'HOT' }).newTier).toBe('HOT')
    expect(adaptProtectResult({ fileId: 'a', protected: true, tierChanged: true, newTier: 'hot' }).newTier).toBe('HOT')
  })
  it('leaves tierChanged/newTier/pinnedAt null on an unprotect response', () => {
    const r = adaptProtectResult({ fileId: 'a', protected: false })
    expect(r.tierChanged).toBeNull()
    expect(r.newTier).toBeNull()
    expect(r.pinnedAt).toBeNull()
  })
  it('carries pinnedAt from a first pin', () => {
    expect(adaptProtectResult({ fileId: 'a', protected: true, pinnedAt: '2026-10-04T01:02:03+00:00' }).pinnedAt).toBe('2026-10-04T01:02:03+00:00')
  })
})
