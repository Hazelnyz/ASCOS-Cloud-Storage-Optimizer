import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Security } from '../Security'

const { useSecuritySummary } = vi.hoisted(() => ({ useSecuritySummary: vi.fn() }))
vi.mock('@/hooks/useSecuritySummary', () => ({ useSecuritySummary }))

const base = {
  authentication: { provider: 'Cognito' as const, lastSignIn: null },
  protectedFiles: { count: 0 },
  anomaly: { status: 'not_connected' as const, rule: 'baseline' as const, lastRun: null, openCount: 0 },
  activity: {
    last24h: { download: 0, write: 0, delete: 0, share: 0 },
    last7d: { download: 0, write: 0, delete: 0, share: 0 },
    truncated: false,
  },
  detections: [] as Array<{
    rule: 'download_volume' | 'delete_volume'
    severity: 'Low' | 'Medium' | 'High'
    status: 'Logged'
    count: number
    threshold: number
    mode: 'learning' | 'baseline'
    windowStart: string
    detectedAt: string
  }>,
}

describe('Security page', () => {
  beforeEach(() => useSecuritySummary.mockReset())

  it('shows loading and no-detection states honestly', () => {
    useSecuritySummary.mockReturnValue({ data: null, error: null, loading: true, reload: vi.fn() })
    const view = render(<Security />)
    expect(screen.getByRole('status', { name: 'Loading security summary' })).toBeInTheDocument()
    view.unmount()

    useSecuritySummary.mockReturnValue({ data: base, error: null, loading: false, reload: vi.fn() })
    render(<Security />)
    expect(screen.getByText('Monitoring pending')).toBeInTheDocument()
    expect(screen.getByText('Rule-based detection is being set up')).toBeInTheDocument()
    expect(screen.getByText('No detections recorded.')).toBeInTheDocument()
    expect(screen.queryByText(/Contained|Step-up required/)).not.toBeInTheDocument()
  })

  it('shows active heartbeat and real detection details without fake response status', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-24T12:30:00Z'))
    useSecuritySummary.mockReturnValue({
      data: {
        ...base,
        anomaly: { status: 'active', rule: 'baseline', lastRun: '2026-10-24T12:15:00Z', openCount: 1 },
        detections: [{
          rule: 'download_volume', severity: 'Medium', status: 'Logged', count: 20,
          threshold: 10, mode: 'learning', windowStart: '2026-10-24T12:00:00Z', detectedAt: '2026-10-24T12:15:00Z',
        }],
      }, error: null, loading: false, reload: vi.fn(),
    })

    render(<Security />)
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByText('Checked 15 minutes ago')).toBeInTheDocument()
    expect(screen.getByText('1 in last 24h')).toBeInTheDocument()
    expect(screen.getByText('Unusual download volume')).toBeInTheDocument()
    expect(screen.getByText('20 events this hour (usual limit: 10)')).toBeInTheDocument()
    expect(screen.getByText('Learning baseline')).toBeInTheDocument()
    expect(screen.getByText('Medium')).toBeInTheDocument()
    expect(screen.getByText('Logged')).toBeInTheDocument()
    expect(screen.queryByText(/Contained|Step-up required/)).not.toBeInTheDocument()
    vi.useRealTimers()
  })
})