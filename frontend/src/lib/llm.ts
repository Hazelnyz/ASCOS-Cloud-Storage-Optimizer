export interface LlmHistoryMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface AskOllamaInput {
  question: string
  history: LlmHistoryMessage[]
  context: string
}

export const OLLAMA_SYSTEM_PROMPT = 'You are the ASCOS assistant. Answer ONLY from the CONTEXT. Be clear and in depth for explanation questions, short for simple ones. If the answer is not in the CONTEXT, say you do not have that information. Do not invent files, numbers, or reasons. Never say you changed or will change a tier. Understand typos and informal phrasing.'

export function sanitizeQuestion(input: string): string {
  return input.replace(/[\u0000-\u001f\u007f-\u009f]/g, '').slice(0, 500).trim()
}

export function isOllamaEnabled(): boolean {
  return import.meta.env.VITE_OLLAMA_ENABLED === 'true'
}

export function ollamaModel(): string {
  return import.meta.env.VITE_OLLAMA_MODEL?.trim() ?? ''
}

export function trimLlmHistory(history: LlmHistoryMessage[]): LlmHistoryMessage[] {
  return history.slice(-6).map((message) => ({ ...message, content: sanitizeQuestion(message.content) }))
}

export async function askOllama({ question, history, context }: AskOllamaInput): Promise<string> {
  const model = ollamaModel()
  if (!model) throw new Error('Local model is not configured')
  const safeQuestion = sanitizeQuestion(question)
  if (!safeQuestion) throw new Error('Question is empty')

  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 45_000)
  try {
    const messages = [
      { role: 'system', content: OLLAMA_SYSTEM_PROMPT },
      ...trimLlmHistory(history).map((message) => ({
        role: message.role,
        content: message.content,
      })),
      { role: 'user', content: `QUESTION:\n${safeQuestion}\n\nCONTEXT:\n${context}` },
    ]
    const response = await fetch('/ollama/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      body: JSON.stringify({ model, messages, stream: false, options: { temperature: 0.2, num_predict: 400 } }),
    })
    if (!response.ok) throw new Error(`Local model returned HTTP ${response.status}`)
    const payload: unknown = await response.json()
    if (typeof payload !== 'object' || payload === null || !('message' in payload)) throw new Error('Malformed local model response')
    const message = (payload as { message?: unknown }).message
    if (typeof message !== 'object' || message === null || !('content' in message)) throw new Error('Malformed local model response')
    const content = (message as { content?: unknown }).content
    if (typeof content !== 'string' || !content.trim()) throw new Error('Local model returned an empty answer')
    return content.trim()
  } finally {
    clearTimeout(timeout)
  }
}
