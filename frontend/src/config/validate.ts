// Pure configuration validation - shared by the runtime (src/config/env.ts) and
// the Vite build (vite.config.ts) so a misconfigured production build fails
// BEFORE it can ship. It must not touch import.meta or any browser API.

export interface BudgetConfig {
  monthlyUsd: number
  alertPercent: number
}

export interface AppConfig {
  apiBaseUrl: string
  cognitoUserPoolId: string
  cognitoClientId: string
  awsRegion: string
  /** Present only when both optional budget variables are set. */
  budget: BudgetConfig | null
  storageRates: { HOT: number; WARM: number; COLD: number } | null
}

export type RawEnv = Record<string, string | boolean | undefined>

export const REQUIRED_ENV_VARS = [
  'VITE_API_BASE_URL',
  'VITE_COGNITO_USER_POOL_ID',
  'VITE_COGNITO_CLIENT_ID',
  'VITE_AWS_REGION',
] as const

export type ValidationResult =
  | { ok: true; config: AppConfig }
  | { ok: false; problems: string[] }

const REGION_RE = /^[a-z]{2}(-[a-z]+)+-\d$/
const POOL_ID_RE = /^([a-z]{2}(?:-[a-z]+)+-\d)_[A-Za-z0-9]+$/
const CLIENT_ID_RE = /^[A-Za-z0-9]{8,}$/

function read(raw: RawEnv, key: string): string {
  const v = raw[key]
  return typeof v === 'string' ? v.trim() : ''
}

function isLocalHost(hostname: string): boolean {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]'
}

/**
 * Validates the environment. Problems name the offending VARIABLE only - never
 * its value - so configuration errors are safe to show on screen and in logs.
 */
export function validateEnv(raw: RawEnv): ValidationResult {
  const problems: string[] = []

  for (const key of REQUIRED_ENV_VARS) {
    if (!read(raw, key)) problems.push(`${key} is not set`)
  }

  let apiBaseUrl = read(raw, 'VITE_API_BASE_URL')
  if (apiBaseUrl) {
    try {
      const url = new URL(apiBaseUrl)
      if (url.protocol !== 'https:' && !(url.protocol === 'http:' && isLocalHost(url.hostname))) {
        problems.push('VITE_API_BASE_URL must use https (http is only allowed for localhost)')
      }
      if (url.search || url.hash) {
        problems.push('VITE_API_BASE_URL must not contain a query string or fragment')
      }
      apiBaseUrl = apiBaseUrl.replace(/\/+$/, '')
    } catch {
      problems.push('VITE_API_BASE_URL is not a valid URL')
    }
  }

  const awsRegion = read(raw, 'VITE_AWS_REGION')
  if (awsRegion && !REGION_RE.test(awsRegion)) {
    problems.push('VITE_AWS_REGION is not a valid AWS region name')
  }

  const poolId = read(raw, 'VITE_COGNITO_USER_POOL_ID')
  if (poolId) {
    const m = POOL_ID_RE.exec(poolId)
    if (!m) {
      problems.push('VITE_COGNITO_USER_POOL_ID is not a valid Cognito user pool ID')
    } else if (awsRegion && REGION_RE.test(awsRegion) && m[1] !== awsRegion) {
      problems.push('VITE_COGNITO_USER_POOL_ID belongs to a different region than VITE_AWS_REGION')
    }
  }

  const clientId = read(raw, 'VITE_COGNITO_CLIENT_ID')
  if (clientId && !CLIENT_ID_RE.test(clientId)) {
    problems.push('VITE_COGNITO_CLIENT_ID is not a valid Cognito app client ID')
  }

  // Optional budget display: both or neither.
  const monthlyRaw = read(raw, 'VITE_BUDGET_MONTHLY_USD')
  const percentRaw = read(raw, 'VITE_BUDGET_ALERT_PERCENT')
  let budget: BudgetConfig | null = null
  if (monthlyRaw || percentRaw) {
    const monthlyUsd = Number(monthlyRaw)
    const alertPercent = Number(percentRaw)
    if (!monthlyRaw || !percentRaw) {
      problems.push('VITE_BUDGET_MONTHLY_USD and VITE_BUDGET_ALERT_PERCENT must be set together')
    } else if (!Number.isFinite(monthlyUsd) || monthlyUsd <= 0) {
      problems.push('VITE_BUDGET_MONTHLY_USD must be a positive number')
    } else if (!Number.isFinite(alertPercent) || alertPercent <= 0 || alertPercent > 100) {
      problems.push('VITE_BUDGET_ALERT_PERCENT must be a number between 1 and 100')
    } else {
      budget = { monthlyUsd, alertPercent }
    }
  }

  const rateKeys = {
    HOT: 'VITE_RATE_HOT_PER_GB_MONTH',
    WARM: 'VITE_RATE_WARM_PER_GB_MONTH',
    COLD: 'VITE_RATE_COLD_PER_GB_MONTH',
  } as const
  const rateValues = Object.fromEntries(
    Object.entries(rateKeys).map(([tier, key]) => [tier, read(raw, key)]),
  ) as Record<keyof typeof rateKeys, string>
  const anyRate = Object.values(rateValues).some(Boolean)
  let storageRates: AppConfig['storageRates'] = null
  if (anyRate) {
    const parsed = Object.fromEntries(
      Object.entries(rateValues).map(([tier, value]) => [tier, Number(value)]),
    ) as Record<keyof typeof rateKeys, number>
    for (const tier of Object.keys(rateKeys) as Array<keyof typeof rateKeys>) {
      if (!rateValues[tier]) problems.push(`${rateKeys[tier]} is not set`)
      else if (!Number.isFinite(parsed[tier]) || parsed[tier] < 0) problems.push(`${rateKeys[tier]} must be a non-negative number`)
    }
    if (Object.values(rateValues).every(Boolean) && Object.values(parsed).every((value) => Number.isFinite(value) && value >= 0)) {
      storageRates = parsed
    }
  }

  if (problems.length > 0) return { ok: false, problems }

  return {
    ok: true,
    config: { apiBaseUrl, cognitoUserPoolId: poolId, cognitoClientId: clientId, awsRegion, budget, storageRates },
  }
}
