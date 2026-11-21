import { describe, expect, it } from 'vitest'
import { adaptSecuritySummary } from '../adapters'
import { ApiError } from '../errors'

const raw = {
  authentication: { provider: 'Cognito', lastSignIn: null },
  protectedFiles: { count: 1 },
  anomaly: { status: 'active', rule: 'baseline', lastRun: '2026-10-24T12:15:00Z', openCount: 1 },
  activity: {
    last24h: { download: 2, write: 0, delete: 0, share: 1 },
    last7d: { download: 4, write: 1, delete: 0, share: 2 },
    truncated: false,
  },
  detections: [{
    rule: 'download_volume', severity: 'Medium', status: 'Logged', count: 20,
    threshold: 10, mode: 'learning', windowStart: '2026-10-24T12:00:00Z', detectedAt: '2026-10-24T12:15:00Z',
  }],
}

describe('adaptSecuritySummary', () => {
  it('maps anomaly heartbeat, activity totals, and persisted detection rows', () => {
    const result = adaptSecuritySummary(raw)
    expect(result.anomaly.status).toBe('active')
    expect(result.anomaly.openCount).toBe(1)
    expect(result.activity.last24h.download).toBe(2)
    expect(result.detections[0]).toMatchObject({ rule: 'download_volume', severity: 'Medium', status: 'Logged', mode: 'learning' })
  })

  it('rejects response statuses and severities that are not from the detection contract', () => {
    expect(() => adaptSecuritySummary({ ...raw, detections: [{ ...raw.detections[0], status: 'Contained' }] })).toThrow(ApiError)
    expect(() => adaptSecuritySummary({ ...raw, detections: [{ ...raw.detections[0], severity: 'Critical' }] })).toThrow(ApiError)
  })
})