import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { CostSummary } from '@/types'
import { api } from '@/services/api'
import { Budget } from '../Budget'

const mockState = vi.hoisted(() => ({ summary: null as CostSummary | null }))
vi.mock('@/services/api', () => ({ api: { getCostSummary: vi.fn(async () => mockState.summary), updateBudget: vi.fn() } }))
vi.mock('@/hooks/useDocumentTitle', () => ({ useDocumentTitle: vi.fn() }))

const makeSummary = (budget: number | null = 100): CostSummary => ({
  budget, alert_threshold: budget === null ? null : 80, estimated_spent: 20,
  breakdown: [
    { category: 'Storage - Hot', amount: 0.1 }, { category: 'Storage - Warm', amount: 0 },
    { category: 'Storage - Cold', amount: 0 }, { category: 'Requests and retrieval', amount: 0.02 },
    { category: 'Shared overhead', amount: 2 },
  ],
  storage_by_tier: {
    HOT: { bytes: 100, gb: 0.0000001, rate: 0.025, cost: 0.1 },
    WARM: { bytes: 0, gb: 0, rate: 0.0138, cost: 0 }, COLD: { bytes: 0, gb: 0, rate: 0.005, cost: 0 },
  },
  rates_used: {
    storage: { HOT: 0.025, WARM: 0.0138, COLD: 0.005 },
    requests: { standard_write: 0.005, standard_read: 0.0004, warm_write: 0.01, warm_read: 0.001, cold_write: 0.02, cold_read: 0.01, delete: 0 },
    retrieval: { warm: 0.01, cold: 0.03 }, notes: 'WARM and COLD request and retrieval rates are approximate.',
  },
  computed_at: '2026-10-28T00:00:00Z', ml_savings_estimate: null,
  budget_config: { min: 0, max: 500, step: 5, alert_threshold_min: 1, alert_threshold_max: 100 },
})

describe('Cost & Budget page', () => {
  beforeEach(() => {
    mockState.summary = makeSummary()
    vi.mocked(api.getCostSummary).mockImplementation(async () => mockState.summary as CostSummary)
    vi.mocked(api.updateBudget).mockImplementation(async (value) => {
      mockState.summary = { ...makeSummary(value.budget), alert_threshold: value.alert_threshold }
      return value
    })
  })

  it('renders per-user estimated monthly budget and the cost breakdown', async () => {
    render(<Budget />)
    expect(await screen.findByLabelText('Budget $100.00 per month')).toBeInTheDocument()
    expect(screen.getByText('$20.00')).toBeInTheDocument()
    expect(screen.getByText('Estimated Cost Breakdown')).toBeInTheDocument()
    expect(screen.getByText('Requests and retrieval')).toBeInTheDocument()
    expect(screen.getByText('Estimated from your files and activity.')).toBeInTheDocument()
    expect(screen.getByText('100 B')).toBeInTheDocument()
    const tooltip = screen.getByRole('tooltip', { hidden: true })
    expect(tooltip.className).toContain('invisible')
    expect(screen.getByRole('button', { name: 'Show cost estimate notes' })).toHaveAttribute('aria-expanded', 'false')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Show cost estimate notes' }))
    expect(screen.getByRole('tooltip', { hidden: true }).className).toContain('visible opacity-100')
    expect(screen.getByRole('tooltip', { hidden: true })).toHaveTextContent('WARM and COLD request and retrieval rates are approximate.')
    expect(screen.queryByText(/ML savings opportunity/)).not.toBeInTheDocument()
  })

  it('formats zero cost as $0.00 and positive sub-cent costs as less than one cent', async () => {
    const zeroSummary = makeSummary()
    mockState.summary = {
      ...zeroSummary,
      estimated_spent: 0,
      breakdown: zeroSummary.breakdown.map((row) => ({ ...row, amount: 0 })),
    }
    const { unmount } = render(<Budget />)
    await screen.findAllByText('$0.00')
    const costCard = screen.getByText('Estimated Cost Breakdown').closest('section')!
    const overviewCard = screen.getByText('Monthly Budget').closest('section')!
    expect(within(costCard).getAllByText('$0.00')).toHaveLength(5)
    expect(within(overviewCard).getByText('$0.00')).toBeInTheDocument()

    mockState.summary = {
      ...makeSummary(),
      estimated_spent: 0.004,
      breakdown: makeSummary().breakdown.map((row) => ({
        ...row,
        amount: row.category === 'Storage - Hot' || row.category === 'Requests and retrieval' ? 0.009 : 0,
      })),
    }
    unmount()
    render(<Budget />)
    await screen.findAllByText('<$0.01')
    expect(screen.getAllByText('<$0.01')).toHaveLength(3)
    expect(within(screen.getByText('Estimated Cost Breakdown').closest('section')!).getAllByText('$0.00')).toHaveLength(3)
    expect(within(screen.getByText('Monthly Budget').closest('section')!).queryByText('$0.00')).not.toBeInTheDocument()
  })

  it('updates the overview from the budget slider and saves the value server-side', async () => {
    const user = userEvent.setup()
    render(<Budget />)
    const slider = await screen.findByRole('slider', { name: 'Monthly budget slider' })
    fireEvent.change(slider, { target: { value: '200' } })
    expect(screen.getByLabelText('Budget $200.00 per month')).toBeInTheDocument()
    expect(screen.getByText('10.0% of budget')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save budget' }))
    await waitFor(() => expect(api.updateBudget).toHaveBeenCalledWith({ budget: 200, alert_threshold: 80 }))
    expect(await screen.findByText('Budget saved to your account.')).toBeInTheDocument()
  })

  it('shows an explicit unavailable value for shared overhead', async () => {
    mockState.summary = { ...makeSummary(), breakdown: makeSummary().breakdown.map((row) => row.category === 'Shared overhead' ? { ...row, amount: null } : row) }
    render(<Budget />)
    expect(await screen.findByText('Not available')).toBeInTheDocument()
  })
})
