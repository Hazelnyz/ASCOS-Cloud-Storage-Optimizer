import { describe, it, expect, vi } from 'vitest'
import { createHttpClient } from '../http'
import { ApiError } from '../errors'

async function catchError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise
    throw new Error('expected the promise to reject')
  } catch (err) {
    if (!(err instanceof ApiError)) throw err
    return err
  }
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('createHttpClient', () => {
  it('attaches the bearer token and parses a successful response', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }))
    const client = createHttpClient({
      baseUrl: 'https://api.example',
      getToken: async () => 'tok-1',
      refreshSession: async () => {},
      onSessionExpired: () => {},
      fetchImpl,
    })
    const result = await client.request({ path: '/files', parse: (r) => r })
    expect(result).toEqual({ ok: true })
    const [, init] = fetchImpl.mock.calls[0]
    expect(init.headers.Authorization).toBe('Bearer tok-1')
  })

  it('on a 401, refreshes the session exactly once and retries with the new token', async () => {
    let calls = 0
    const fetchImpl = vi.fn().mockImplementation(() => {
      calls += 1
      return Promise.resolve(calls === 1 ? jsonResponse(401, { error: 'Unauthorized' }) : jsonResponse(200, { ok: true }))
    })
    const refreshSession = vi.fn().mockResolvedValue(undefined)
    const onSessionExpired = vi.fn()
    const client = createHttpClient({
      baseUrl: 'https://api.example', getToken: async () => 'tok', refreshSession, onSessionExpired, fetchImpl,
    })
    const result = await client.request({ path: '/files', parse: (r) => r })
    expect(result).toEqual({ ok: true })
    expect(refreshSession).toHaveBeenCalledTimes(1)
    expect(onSessionExpired).not.toHaveBeenCalled()
  })

  it('signs the user out after a second consecutive 401 (no infinite retry loop)', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(401, { error: 'Unauthorized' }))
    const refreshSession = vi.fn().mockResolvedValue(undefined)
    const onSessionExpired = vi.fn()
    const client = createHttpClient({
      baseUrl: 'https://api.example', getToken: async () => 'tok', refreshSession, onSessionExpired, fetchImpl,
    })
    await expect(client.request({ path: '/files', parse: (r) => r })).rejects.toThrow(ApiError)
    expect(fetchImpl).toHaveBeenCalledTimes(2)
    expect(refreshSession).toHaveBeenCalledTimes(1)
    expect(onSessionExpired).toHaveBeenCalledTimes(1)
  })

  it('maps a 404 to ApiError kind not_found without retrying', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(404, { error: 'File not found' }))
    const client = createHttpClient({
      baseUrl: 'https://api.example', getToken: async () => 'tok', refreshSession: async () => {}, onSessionExpired: () => {}, fetchImpl,
    })
    const err = await catchError(client.request({ path: '/files/x', parse: (r) => r }))
    expect(err.kind).toBe('not_found')
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('retries a GET on a 503 up to the configured limit, then succeeds', async () => {
    let calls = 0
    const fetchImpl = vi.fn().mockImplementation(() => {
      calls += 1
      return Promise.resolve(calls < 3 ? jsonResponse(503, {}) : jsonResponse(200, { ok: true }))
    })
    const client = createHttpClient({
      baseUrl: 'https://api.example', getToken: async () => 'tok', refreshSession: async () => {}, onSessionExpired: () => {},
      fetchImpl, sleep: async () => {},
    })
    const result = await client.request({ path: '/files', parse: (r) => r })
    expect(result).toEqual({ ok: true })
    expect(calls).toBe(3)
  })

  it('does not retry a POST on a 503 (not idempotent)', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(503, {}))
    const client = createHttpClient({
      baseUrl: 'https://api.example', getToken: async () => 'tok', refreshSession: async () => {}, onSessionExpired: () => {}, fetchImpl,
    })
    await expect(client.request({ method: 'POST', path: '/files/upload-url', body: {}, parse: (r) => r })).rejects.toThrow(ApiError)
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('maps a network failure to ApiError kind network', async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    const client = createHttpClient({
      baseUrl: 'https://api.example', getToken: async () => 'tok', refreshSession: async () => {}, onSessionExpired: () => {},
      fetchImpl, maxGetRetries: 0,
    })
    const err = await catchError(client.request({ path: '/files', parse: (r) => r }))
    expect(err.kind).toBe('network')
  })

  it('never sends raw fetch/parse errors as the request result - malformed JSON becomes ApiError', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response('not json', { status: 200 }))
    const client = createHttpClient({
      baseUrl: 'https://api.example', getToken: async () => 'tok', refreshSession: async () => {}, onSessionExpired: () => {}, fetchImpl,
    })
    const err = await catchError(client.request({ path: '/files', parse: (r) => r }))
    expect(err.kind).toBe('malformed')
  })
})
