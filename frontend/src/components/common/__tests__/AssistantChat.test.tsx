import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/services/api'
import { AssistantChat } from '../AssistantChat'

vi.mock('@/services/api', () => ({
  api: {
    getFrequentlyUsed: vi.fn().mockResolvedValue([]),
    listFiles: vi.fn().mockResolvedValue([]),
  },
}))

describe('AssistantChat', () => {
  afterEach(() => vi.unstubAllGlobals())
  beforeEach(() => {
    vi.mocked(api.getFrequentlyUsed).mockResolvedValue([])
    vi.mocked(api.listFiles).mockResolvedValue([])
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    })
  })

  it('renders the updated built-in answers footer', async () => {
    const user = userEvent.setup()
    render(<AssistantChat />)
    await user.click(screen.getByRole('button', { name: 'Open assistant' }))
    expect(await screen.findByText("Answers are built from your files' stored model data (SHAP reasons, scores, tier policy) and LLM.")).toBeInTheDocument()
  })

  it('opens, answers help on Enter, and closes on Escape', async () => {
    const user = userEvent.setup()
    render(<AssistantChat />)

    await user.click(screen.getByRole('button', { name: 'Open assistant' }))
    expect(screen.getByRole('dialog', { name: 'ASCOS Assistant' })).toBeInTheDocument()

    const input = await screen.findByPlaceholderText('Ask a question...')
    await user.type(input, 'help{Enter}')

    expect(await screen.findByText(/Try asking:/)).toBeInTheDocument()

    fireEvent.keyDown(input, { key: 'Escape' })
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'ASCOS Assistant' })).not.toBeInTheDocument()
    })
  })

  it('answers with file IDs and discloses when the file list fails', async () => {
    vi.mocked(api.getFrequentlyUsed).mockResolvedValueOnce([{
      fileId: '7b12cdef-1234',
      pAccess: 0.85,
      candidateTiers: ['HOT'],
      banditChoice: 'HOT',
      predictionTimestamp: '2024-01-01T00:00:00Z',
      topReasons: null,
    }])
    vi.mocked(api.listFiles).mockRejectedValueOnce(new Error('file list unavailable'))

    const user = userEvent.setup()
    render(<AssistantChat />)
    await user.click(screen.getByRole('button', { name: 'Open assistant' }))

    const input = await screen.findByPlaceholderText('Ask a question...')
    await waitFor(() => expect(input).toBeEnabled())
    await user.type(input, 'Why was 7b12cdef moved?{Enter}')

    expect(await screen.findByText(/7b12cdef-1234 has a p_access score of 85%/)).toBeInTheDocument()
    expect(screen.getByText(/File names could not be loaded, so I'm using file IDs/)).toBeInTheDocument()
  })

  it('falls back to built-in answers when the enabled local model returns malformed data', async () => {
    vi.stubEnv('VITE_OLLAMA_ENABLED', 'true')
    vi.stubEnv('VITE_OLLAMA_MODEL', 'llama3.2:3b')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => { throw new SyntaxError('invalid JSON') } }))
    const user = userEvent.setup()
    render(<AssistantChat />)
    await user.click(screen.getByRole('button', { name: 'Open assistant' }))
    const input = await screen.findByPlaceholderText('Ask a question...')
    await waitFor(() => expect(input).toBeEnabled())
    await user.type(input, 'help{Enter}')
    expect(await screen.findByText(/Try asking:/)).toBeInTheDocument()
    expect(screen.getByText('Built-in answer (local model unavailable)')).toBeInTheDocument()
  })

  it.each(['HTTP error', 'timeout/network error'])('falls back to built-in answers after an Ollama %s', async (failure) => {
    vi.stubEnv('VITE_OLLAMA_ENABLED', 'true')
    vi.stubEnv('VITE_OLLAMA_MODEL', 'llama3.2:3b')
    vi.stubGlobal('fetch', vi.fn(() => failure === 'HTTP error'
      ? Promise.resolve({ ok: false, status: 503 })
      : Promise.reject(new Error('request timed out'))))
    const user = userEvent.setup()
    render(<AssistantChat />)
    await user.click(screen.getByRole('button', { name: 'Open assistant' }))
    const input = await screen.findByPlaceholderText('Ask a question...')
    await waitFor(() => expect(input).toBeEnabled())
    await user.type(input, 'help{Enter}')
    expect(await screen.findByText(/Try asking:/)).toBeInTheDocument()
    expect(screen.getByText('Built-in answer (local model unavailable)')).toBeInTheDocument()
  })

  it('does not show the built-in fallback caption for an Ollama answer', async () => {
    vi.stubEnv('VITE_OLLAMA_ENABLED', 'true')
    vi.stubEnv('VITE_OLLAMA_MODEL', 'llama3.2:3b')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ message: { content: 'Local model answer.' } }),
    }))
    const user = userEvent.setup()
    render(<AssistantChat />)
    await user.click(screen.getByRole('button', { name: 'Open assistant' }))
    const input = await screen.findByPlaceholderText('Ask a question...')
    await waitFor(() => expect(input).toBeEnabled())
    await user.type(input, 'help{Enter}')
    expect(await screen.findByText('Local model answer.')).toBeInTheDocument()
    expect(screen.queryByText('Built-in answer (local model unavailable)')).not.toBeInTheDocument()
  })

  it('uses only the rule engine when the local model setting is disabled', async () => {
    vi.stubEnv('VITE_OLLAMA_ENABLED', 'false')
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<AssistantChat />)
    await user.click(screen.getByRole('button', { name: 'Open assistant' }))
    const input = await screen.findByPlaceholderText('Ask a question...')
    await waitFor(() => expect(input).toBeEnabled())
    await user.type(input, 'help{Enter}')
    expect(await screen.findByText(/Try asking:/)).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
