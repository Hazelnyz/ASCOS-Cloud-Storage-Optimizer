// Runtime configuration. The single place that reads import.meta.env.
// There is deliberately NO mock/demo mode: if configuration is missing the app
// shows a configuration error instead of pretending to work.

import { validateEnv, type AppConfig } from './validate'

export class ConfigError extends Error {
  readonly problems: string[]
  constructor(problems: string[]) {
    super(`Invalid ASCOS frontend configuration: ${problems.join('; ')}`)
    this.name = 'ConfigError'
    this.problems = problems
  }
}

let cached: AppConfig | null = null

export function getConfig(): AppConfig {
  if (cached) return cached
  const result = validateEnv(import.meta.env as unknown as Record<string, string | undefined>)
  if (!result.ok) throw new ConfigError(result.problems)
  cached = result.config
  return cached
}

/** Test seam: drop the memoised config. */
export function resetConfigCache(): void {
  cached = null
}
