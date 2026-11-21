import { describe, expect, it } from 'vitest'
import { budgetAlertAmount, budgetRemaining, budgetUsagePercent, formatEstimatedUsd } from '../budget'

describe('budget estimate helpers', () => {
  it('calculates current usage and remaining amount from the estimate and selected budget', () => {
    expect(budgetUsagePercent(25, 100)).toBe(25)
    expect(budgetRemaining(25, 100)).toBe(75)
  })

  it('calculates the alert amount from the budget threshold', () => {
    expect(budgetAlertAmount(250, 80)).toBe(200)
  })

  it('keeps unset and zero budgets unavailable instead of inventing a percentage', () => {
    expect(budgetUsagePercent(10, null)).toBeNull()
    expect(budgetUsagePercent(10, 0)).toBeNull()
    expect(budgetRemaining(10, null)).toBeNull()
    expect(budgetAlertAmount(null, 80)).toBeNull()
  })

  it('shows exact zero and preserves positive sub-cent estimates', () => {
    expect(formatEstimatedUsd(0)).toBe('$0.00')
    expect(formatEstimatedUsd(0.00001)).toBe('<$0.01')
    expect(formatEstimatedUsd(0.00999)).toBe('<$0.01')
    expect(formatEstimatedUsd(0.01)).toBe('$0.01')
  })
})
