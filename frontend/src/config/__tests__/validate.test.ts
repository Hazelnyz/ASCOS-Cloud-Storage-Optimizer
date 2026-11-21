import { describe, it, expect } from 'vitest'
import { validateEnv } from '../validate'

const VALID = {
  VITE_API_BASE_URL: 'https://abc123.execute-api.ap-south-1.amazonaws.com',
  VITE_COGNITO_USER_POOL_ID: 'ap-south-1_ABCDEFGHI',
  VITE_COGNITO_CLIENT_ID: 'abcdefghijklmnopqrstuvwxyz012345',
  VITE_AWS_REGION: 'ap-south-1',
}

describe('validateEnv', () => {
  it('accepts a fully valid configuration', () => {
    const result = validateEnv(VALID)
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.config.apiBaseUrl).toBe(VALID.VITE_API_BASE_URL)
      expect(result.config.budget).toBeNull()
    }
  })

  it('reports every missing required variable, not just the first', () => {
    const result = validateEnv({})
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.problems).toHaveLength(4)
      expect(result.problems.join(' ')).toContain('VITE_API_BASE_URL')
      expect(result.problems.join(' ')).toContain('VITE_COGNITO_USER_POOL_ID')
    }
  })

  it('strips a trailing slash from the API base URL', () => {
    const result = validateEnv({ ...VALID, VITE_API_BASE_URL: `${VALID.VITE_API_BASE_URL}/` })
    expect(result.ok && result.config.apiBaseUrl).toBe(VALID.VITE_API_BASE_URL)
  })

  it('rejects a query string or fragment on the API base URL', () => {
    const result = validateEnv({ ...VALID, VITE_API_BASE_URL: `${VALID.VITE_API_BASE_URL}?x=1` })
    expect(result.ok).toBe(false)
  })

  it('allows http only for localhost', () => {
    const local = validateEnv({ ...VALID, VITE_API_BASE_URL: 'http://localhost:4566' })
    expect(local.ok).toBe(true)
    const remote = validateEnv({ ...VALID, VITE_API_BASE_URL: 'http://example.com' })
    expect(remote.ok).toBe(false)
  })

  it('rejects a Cognito pool ID from a different region than VITE_AWS_REGION', () => {
    const result = validateEnv({ ...VALID, VITE_COGNITO_USER_POOL_ID: 'us-east-1_ABCDEFGHI' })
    expect(result.ok).toBe(false)
  })

  it('requires the budget variables together, not one alone', () => {
    const result = validateEnv({ ...VALID, VITE_BUDGET_MONTHLY_USD: '100' })
    expect(result.ok).toBe(false)
  })

  it('accepts a valid budget pair', () => {
    const result = validateEnv({ ...VALID, VITE_BUDGET_MONTHLY_USD: '100', VITE_BUDGET_ALERT_PERCENT: '80' })
    expect(result.ok && result.config.budget).toEqual({ monthlyUsd: 100, alertPercent: 80 })
  })

  it('rejects an alert percent outside 1-100', () => {
    const result = validateEnv({ ...VALID, VITE_BUDGET_MONTHLY_USD: '100', VITE_BUDGET_ALERT_PERCENT: '150' })
    expect(result.ok).toBe(false)
  })
})
