import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Analytics } from '../Analytics'

const { useAnalyticsSummary } = vi.hoisted(() => ({ useAnalyticsSummary: vi.fn() }))

vi.mock('@/hooks/useAnalyticsSummary', () => ({ useAnalyticsSummary }))

describe('Analytics page', () => {
  beforeEach(() => {
    useAnalyticsSummary.mockReset()
    globalThis.ResizeObserver = class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  })

  it('shows a skeleton while the summary loads', () => {
    useAnalyticsSummary.mockReturnValue({ data: null, error: null, loading: true, reload: vi.fn() })

    render(<Analytics />)

    expect(screen.getByRole('status', { name: 'Loading analytics' })).toBeInTheDocument()
  })

  it('shows chart-specific empty messages and hides unavailable optimization', () => {
    useAnalyticsSummary.mockReturnValue({
      data: { tiers: [], types: [], storageOverTime: [], access: [], optimization: null },
      error: null,
      loading: false,
      reload: vi.fn(),
    })

    render(<Analytics />)

    expect(screen.getAllByText('No files uploaded yet.')).toHaveLength(3)
    expect(screen.getByText('Access activity will appear once reads, writes and downloads are logged.')).toBeInTheDocument()
    expect(screen.queryByText(/Estimated optimization opportunity/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Demo data/i)).not.toBeInTheDocument()
    expect(screen.queryByText('Not enough data yet')).not.toBeInTheDocument()
  })

  it('renders actual summary labels and the savings banner when predictions exist', () => {
    useAnalyticsSummary.mockReturnValue({
      data: {
        tiers: [{ tier: 'HOT', files: 2, bytes: 2048 }],
        types: [{ type: 'pdf', files: 2 }],
        storageOverTime: [{ day: '2026-10-23', bytes: 2048 }],
        access: [{ day: '2026-10-23', reads: 1, writes: 0, downloads: 1 }],
        optimization: { monthlySavings: 0.25 },
      },
      error: null,
      loading: false,
      reload: vi.fn(),
    })

    render(<Analytics />)

    expect(screen.getByText('Estimated optimization opportunity')).toBeInTheDocument()
    expect(screen.getByText('$0.25 / month')).toBeInTheDocument()
    expect(screen.getByText('Storage Usage Over Time')).toBeInTheDocument()
    expect(screen.getByText('Storage Tier Distribution')).toBeInTheDocument()
    expect(screen.getByText('Files by Type')).toBeInTheDocument()
    expect(screen.getByText('Access Activity')).toBeInTheDocument()
  })
})