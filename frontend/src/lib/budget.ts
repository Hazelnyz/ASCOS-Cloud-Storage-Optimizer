import { formatUsd } from './format'

export function budgetUsagePercent(estimatedSpent: number, budget: number | null): number | null {
  return budget !== null && budget > 0 ? estimatedSpent / budget * 100 : null
}

export function budgetRemaining(estimatedSpent: number, budget: number | null): number | null {
  return budget === null ? null : budget - estimatedSpent
}

export function budgetAlertAmount(budget: number | null, thresholdPercent: number | null): number | null {
  return budget === null || thresholdPercent === null ? null : budget * thresholdPercent / 100
}

export function formatEstimatedUsd(amount: number): string {
  if (amount === 0) return formatUsd(0)
  if (amount > 0 && amount < 0.01) return '<$0.01'
  return formatUsd(amount)
}
