import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { FileSummary, Prediction } from '@/types'
import { buildAssistantContext, enrichPredictions } from '../explain'
import { askOllama, isOllamaEnabled, trimLlmHistory } from '../llm'

const prediction = (fileId: string, timestamp: string): Prediction => ({
  fileId, pAccess: 0.85, candidateTiers: ['HOT'], banditChoice: 'HOT', predictionTimestamp: timestamp,
  topReasons: [{ feature: 'days_since_last_access', contribution: '+1.25' }, { feature: 'file_age_days', contribution: '-0.2' }],
})
const file = (fileId: string): FileSummary => ({
  fileId, filename: `${fileId}.txt`, size: 12, lastModified: '2026-01-01T00:00:00Z', storageClass: 'STANDARD',
  uploadedAt: null, protected: false, pinnedAt: null,
})

describe('Ollama context builder', () => {
  const rows = Array.from({ length: 35 }, (_, index) => prediction(`file-${index}`, `2026-01-${String(index + 1).padStart(2, '0')}T00:00:00Z`))
  const enriched = enrichPredictions(rows, rows.map((row) => file(row.fileId!)))

  it('caps context to 30 files while keeping a specifically named file in full', () => {
    const context = JSON.parse(buildAssistantContext('Why was file-34.txt moved?', enriched))
    expect(context.files).toHaveLength(30)
    expect(context.files.some((row: { fileId: string }) => row.fileId === 'file-34')).toBe(true)
    expect(context.files[29]).toMatchObject({ filename: 'file-34.txt', currentTier: 'HOT', p_access_score: 0.85, policy_band: 'HOT', candidateTiers: ['HOT'], recommendedTier: 'HOT', pinned: false })
  })

  it('includes the focused rule-engine reference answer, friendly signed reasons and policy facts', () => {
    const context = JSON.parse(buildAssistantContext('Why was file-0.txt moved?', enriched))
    expect(context.focusedFile).toBe('file-0')
    expect(context.referenceAnswer).toContain('file-0.txt has a p_access score of 85%')
    expect(context.files[0].topShapReasons).toEqual([
      { feature: 'days since last access', signedValue: '+1.25' },
      { feature: 'file age in days', signedValue: '-0.2' },
    ])
    expect(context.policyFacts).toContain('p_access >= 0.8')
    expect(context.policyFacts).toContain('Pinned files are never moved automatically')
    expect(context.policyFacts).toContain('SHAP values are model log-odds')
    expect(context.policyFacts).toContain('synthetic data')
  })
})

describe('askOllama', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_OLLAMA_MODEL', 'llama3.2:3b')
  })

  it('sends configured model, constrained generation options and returns the answer', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ message: { content: 'A grounded answer.' } }) })
    vi.stubGlobal('fetch', fetchMock)
    await expect(askOllama({ question: '  explain this  ', history: [], context: '{"files":[]}' })).resolves.toBe('A grounded answer.')
    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(fetchMock.mock.calls[0][0]).toBe('/ollama/api/chat')
    expect(body.model).toBe('llama3.2:3b')
    expect(body.options).toEqual({ temperature: 0.2, num_predict: 400 })
    expect(body.messages[0].content).toContain('Answer ONLY from the CONTEXT')
    expect(body.messages[1].content).toContain('explain this')
  })

  it('aborts at the 45 second timeout', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    })))
    const pending = expect(askOllama({ question: 'hello', history: [], context: '{}' })).rejects.toThrow()
    await vi.advanceTimersByTimeAsync(45_000)
    await pending
    vi.useRealTimers()
  })

  it('rejects HTTP errors and malformed JSON shapes', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce({ ok: false, status: 503 }).mockResolvedValueOnce({ ok: true, json: async () => ({ response: 'wrong shape' }) }))
    await expect(askOllama({ question: 'hello', history: [], context: '{}' })).rejects.toThrow('HTTP 503')
    await expect(askOllama({ question: 'hello', history: [], context: '{}' })).rejects.toThrow('Malformed')
  })

  it('rejects invalid JSON responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => { throw new SyntaxError('invalid JSON') } }))
    await expect(askOllama({ question: 'hello', history: [], context: '{}' })).rejects.toThrow('invalid JSON')
  })

  it('trims history to six recent messages', () => {
    const history = Array.from({ length: 8 }, (_, index) => ({ role: index % 2 ? 'assistant' as const : 'user' as const, content: `message ${index}` }))
    expect(trimLlmHistory(history).map((row) => row.content)).toEqual(['message 2', 'message 3', 'message 4', 'message 5', 'message 6', 'message 7'])
  })
})

describe('Ollama opt-in setting', () => {
  it('is off unless explicitly enabled', () => {
    vi.stubEnv('VITE_OLLAMA_ENABLED', '')
    expect(isOllamaEnabled()).toBe(false)
    vi.stubEnv('VITE_OLLAMA_ENABLED', 'false')
    expect(isOllamaEnabled()).toBe(false)
    vi.stubEnv('VITE_OLLAMA_ENABLED', 'true')
    expect(isOllamaEnabled()).toBe(true)
  })
})
