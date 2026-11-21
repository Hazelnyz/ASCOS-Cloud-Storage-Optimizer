// HTTP client for the ASCOS API (API Gateway HTTP API + Cognito JWT authorizer).
//
// Responsibilities: attach the Cognito access token, enforce a timeout, retry
// idempotent GETs on transient failures, refresh the session ONCE on a 401,
// and map every failure to a safe ApiError. Nothing else in the app calls
// fetch() against the API.

import { ApiError, type ApiErrorKind } from './errors'

export interface HttpClientOptions {
  baseUrl: string
  /** Returns a currently valid access token (refreshing transparently if needed). */
  getToken: () => Promise<string>
  /** Forces a session refresh; called once after a 401. */
  refreshSession: () => Promise<void>
  /** Called when the session cannot be recovered (second 401 / no token). */
  onSessionExpired: () => void
  fetchImpl?: typeof fetch
  timeoutMs?: number
  maxGetRetries?: number
  sleep?: (ms: number) => Promise<void>
}

export interface RequestOptions<T> {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  path: string
  body?: unknown
  signal?: AbortSignal
  /** Validates/maps the parsed JSON body; throw ApiError('malformed') on mismatch. */
  parse: (raw: unknown) => T
}

const DEFAULT_TIMEOUT_MS = 15_000
const DEFAULT_MAX_GET_RETRIES = 2
const RETRYABLE_STATUS = new Set([429, 502, 503, 504])

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

function kindForStatus(status: number): ApiErrorKind {
  if (status === 400 || status === 422) return 'validation'
  if (status === 401) return 'unauthorized'
  if (status === 403) return 'forbidden'
  if (status === 404) return 'not_found'
  if (status === 409) return 'conflict'
  if (status === 429) return 'rate_limited'
  return 'server'
}

export interface HttpClient {
  request<T>(options: RequestOptions<T>): Promise<T>
}

export function createHttpClient(opts: HttpClientOptions): HttpClient {
  const fetchImpl = opts.fetchImpl ?? ((...args: Parameters<typeof fetch>) => fetch(...args))
  const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS
  const maxGetRetries = opts.maxGetRetries ?? DEFAULT_MAX_GET_RETRIES
  const sleep = opts.sleep ?? defaultSleep

  async function sendOnce(o: RequestOptions<unknown>, token: string): Promise<Response> {
    const controller = new AbortController()
    let timedOut = false
    const timer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, timeoutMs)
    const onExternalAbort = () => controller.abort()
    if (o.signal) {
      if (o.signal.aborted) controller.abort()
      else o.signal.addEventListener('abort', onExternalAbort, { once: true })
    }

    try {
      const headers: Record<string, string> = { Authorization: `Bearer ${token}`, Accept: 'application/json' }
      if (o.body !== undefined) headers['Content-Type'] = 'application/json'
      return await fetchImpl(`${opts.baseUrl}${o.path}`, {
        method: o.method ?? 'GET',
        headers,
        body: o.body === undefined ? undefined : JSON.stringify(o.body),
        signal: controller.signal,
      })
    } catch (err) {
      if (o.signal?.aborted) throw new ApiError('aborted')
      if (timedOut) throw new ApiError('timeout')
      if (err instanceof DOMException && err.name === 'AbortError') throw new ApiError('aborted')
      throw new ApiError('network')
    } finally {
      clearTimeout(timer)
      o.signal?.removeEventListener('abort', onExternalAbort)
    }
  }

  async function acquireToken(): Promise<string> {
    try {
      return await opts.getToken()
    } catch {
      opts.onSessionExpired()
      throw new ApiError('unauthorized', 401)
    }
  }

  async function request<T>(o: RequestOptions<T>): Promise<T> {
    const isGet = (o.method ?? 'GET') === 'GET'
    let refreshed = false
    let retries = 0

    for (;;) {
      const token = await acquireToken()
      let response: Response
      try {
        response = await sendOnce(o, token)
      } catch (err) {
        if (isGet && err instanceof ApiError && err.kind === 'network' && retries < maxGetRetries) {
          await sleep(250 * 3 ** retries)
          retries += 1
          continue
        }
        throw err
      }

      if (response.status === 401) {
        if (refreshed) {
          opts.onSessionExpired()
          throw new ApiError('unauthorized', 401)
        }
        refreshed = true
        try {
          await opts.refreshSession()
        } catch {
          opts.onSessionExpired()
          throw new ApiError('unauthorized', 401)
        }
        continue // retry exactly once with the refreshed token
      }

      if (!response.ok) {
        if (isGet && RETRYABLE_STATUS.has(response.status) && retries < maxGetRetries) {
          await sleep(250 * 3 ** retries)
          retries += 1
          continue
        }
        throw new ApiError(kindForStatus(response.status), response.status)
      }

      let parsed: unknown
      try {
        const text = await response.text()
        parsed = text ? JSON.parse(text) : undefined
      } catch {
        throw new ApiError('malformed', response.status)
      }
      return o.parse(parsed)
    }
  }

  return { request }
}
