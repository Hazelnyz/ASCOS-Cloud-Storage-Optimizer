import { useState, useEffect, useRef } from 'react'
import { MessageCircle, X, Send } from 'lucide-react'
import { useAsyncData } from '@/hooks/useAsyncData'
import { api } from '@/services/api'
import { answerQuestion, buildAssistantContext, enrichPredictions, type EnrichedPrediction } from '@/lib/explain'
import { askOllama, isOllamaEnabled, ollamaModel, sanitizeQuestion } from '@/lib/llm'
import type { Prediction } from '@/types'

interface Message {
  id: string
  role: 'user' | 'assistant'
  text: string
  source?: 'local' | 'builtin'
  fallback?: boolean
  model?: string
}

interface AssistantData {
  predictions: EnrichedPrediction[]
}

const SUGGESTED_QUESTIONS = [
  'What is p_access?',
  'Which files are most likely to be accessed?',
  'How many files are in each tier?',
  'Why was a file moved to HOT?'
]

export function AssistantChat() {
  const [isOpen, setIsOpen] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isTyping, setIsTyping] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const warmedModelRef = useRef(false)

  const { data, error, loading } = useAsyncData<AssistantData>(
    async (signal) => {
      if (!isOpen) return { predictions: [] }

      const [predictionResult, fileResult] = await Promise.allSettled([
        api.getFrequentlyUsed({ signal }),
        api.listFiles({ signal }),
      ])
      if (predictionResult.status === 'rejected') throw predictionResult.reason

      const predictionRows = predictionResult.value as Prediction[]
      const files = fileResult.status === 'fulfilled' ? fileResult.value : null
      return {
        predictions: enrichPredictions(
          predictionRows,
          files,
          fileResult.status === 'rejected',
        ),
      }
    },
    [isOpen] // Re-fetch when panel opens
  )

  const predictions = data?.predictions ?? []

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Focus input when opening
  useEffect(() => {
    if (isOpen) {
      inputRef.current?.focus()
      if (isOllamaEnabled() && !warmedModelRef.current) {
        warmedModelRef.current = true
        void askOllama({ question: 'Reply with OK.', history: [], context: 'Warm-up request only.' }).catch(() => undefined)
      }
    }
  }, [isOpen])

  useEffect(() => {
    if (!isOpen) return
    const handleWindowKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsOpen(false)
    }
    window.addEventListener('keydown', handleWindowKeyDown)
    return () => window.removeEventListener('keydown', handleWindowKeyDown)
  }, [isOpen])

  // Add greeting on first open
  useEffect(() => {
    if (isOpen && messages.length === 0) {
      setMessages([{
        id: 'greeting',
        role: 'assistant',
        text: 'Hi! I can answer questions about your file predictions, tier recommendations, and access probabilities. Ask me anything!'
      }])
    }
  }, [isOpen, messages.length])

  const handleSend = async (text: string) => {
    const question = sanitizeQuestion(text)
    if (!question) return

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      text: question
    }

    setMessages(prev => [...prev, userMessage])
    setInput('')
    setIsTyping(true)

    let responseText: string
    let source: Message['source'] = 'builtin'
    let fallback = false
    let model: string | undefined
    if (isOllamaEnabled()) {
      try {
        const context = buildAssistantContext(question, predictions)
        const history = messages.slice(-6).map(({ role, text: content }) => ({ role, content }))
        responseText = await askOllama({ question, history, context })
        source = 'local'
        model = ollamaModel()
      } catch {
        responseText = answerQuestion(question, predictions).text
        fallback = true
      }
    } else {
      await new Promise((resolve) => window.setTimeout(resolve, 300))
      responseText = answerQuestion(question, predictions).text
    }
    const assistantMessage: Message = { id: (Date.now() + 1).toString(), role: 'assistant', text: responseText, source, fallback, model }
    setMessages(prev => [...prev, assistantMessage])
    setIsTyping(false)
  }

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      handleSend(input)
    }
  }

  const handleSuggestedQuestion = (question: string) => {
    handleSend(question)
  }

  const latestAssistantMessage = [...messages].reverse().find((message) => message.role === 'assistant')

  if (!isOpen) {
    // Floating chat icon
    return (
      <button
        onClick={() => setIsOpen(true)}
        className="fixed bottom-5 right-5 z-[100] flex h-12 w-12 items-center justify-center rounded-full bg-accent text-white shadow-lg transition-colors hover:bg-accent/90 focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface"
        aria-label="Open assistant"
      >
        <MessageCircle className="h-5 w-5" />
      </button>
    )
  }

  return (
    <div
      role="dialog"
      aria-label="ASCOS Assistant"
      className="fixed bottom-4 right-4 z-[100] flex flex-col rounded-xl border border-surface-border bg-surface-card shadow-xl transition-all duration-200 ease-in-out"
      style={{ width: 'min(380px, calc(100vw - 32px))', height: '440px', maxHeight: 'calc(100dvh - 32px)' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-surface-border px-4 py-3">
        <h3 className="text-sm font-semibold text-slate-100">ASCOS Assistant</h3>
        <button
          onClick={() => setIsOpen(false)}
          className="rounded p-1 text-slate-400 transition-colors hover:text-slate-200 focus:outline-none focus:ring-2 focus:ring-slate-400"
          aria-label="Close assistant"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {loading && messages.length === 1 ? (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <div className="flex gap-1">
              <span className="h-2 w-2 animate-bounce rounded-full bg-slate-500" style={{ animationDelay: '0ms' }} />
              <span className="h-2 w-2 animate-bounce rounded-full bg-slate-500" style={{ animationDelay: '150ms' }} />
              <span className="h-2 w-2 animate-bounce rounded-full bg-slate-500" style={{ animationDelay: '300ms' }} />
            </div>
            <span>Loading predictions and file names...</span>
          </div>
        ) : error ? (
          <div className="text-sm text-red-400">
            Failed to load predictions. Please try again later.
          </div>
        ) : (
          <div className="space-y-3">
            {messages.map((message) => (
              <div
                key={message.id}
                className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                {message.role === 'user' ? (
                  <div className="max-w-[85%] rounded-lg bg-slate-600 px-3 py-2 text-sm text-white">
                    {message.text}
                  </div>
                ) : (
                  <div className="max-w-[90%]">
                    <div className="rounded-lg bg-slate-800 px-3 py-2 text-sm text-slate-200">
                      {message.text}
                    </div>
                    {message.fallback && message.source === 'builtin' && (
                      <p className="mt-1 whitespace-nowrap text-xs text-slate-500">Built-in answer (local model unavailable)</p>
                    )}
                  </div>
                )}
              </div>
            ))}
            {isTyping && (
              <div className="flex justify-start">
                <div className="flex gap-1 rounded-lg bg-slate-800 px-3 py-2">
                  <span className="h-2 w-2 animate-bounce rounded-full bg-slate-500" style={{ animationDelay: '0ms' }} />
                  <span className="h-2 w-2 animate-bounce rounded-full bg-slate-500" style={{ animationDelay: '150ms' }} />
                  <span className="h-2 w-2 animate-bounce rounded-full bg-slate-500" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Suggested questions */}
      {!loading && !error && messages.length <= 2 && (
        <div className="border-t border-surface-border px-4 py-3">
          <div className="flex flex-wrap gap-2">
            {SUGGESTED_QUESTIONS.map((question) => (
              <button
                key={question}
                onClick={() => handleSuggestedQuestion(question)}
                className="rounded-full border border-slate-600 bg-slate-800 px-3 py-1.5 text-xs text-slate-300 transition-colors hover:bg-slate-700 hover:text-slate-200 focus:outline-none focus:ring-2 focus:ring-slate-400"
              >
                {question}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input */}
      <div className="border-t border-surface-border px-4 py-3">
        <div className="flex items-center gap-2">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value.replace(/[\u0000-\u001f\u007f-\u009f]/g, '').slice(0, 500))}
            onKeyDown={handleKeyDown}
            placeholder="Ask a question..."
            className="flex-1 rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500 disabled:opacity-50"
            disabled={loading || isTyping}
          />
          <button
            onClick={() => handleSend(input)}
            disabled={!input.trim() || loading || isTyping}
            className="rounded-lg bg-slate-600 p-2 text-white transition-colors hover:bg-slate-500 disabled:opacity-50 disabled:hover:bg-slate-600 focus:outline-none focus:ring-2 focus:ring-slate-400"
            aria-label="Send message"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Footer */}
      <div className="border-t border-surface-border px-4 py-2">
        {latestAssistantMessage?.source === 'local'
          ? <p className="text-xs text-slate-600">Generated by a local language model ({latestAssistantMessage.model}) from your files' stored model data; it can make mistakes.</p>
          : <p className="text-xs text-slate-600">Answers are built from your files' stored model data (SHAP reasons, scores, tier policy) and LLM.</p>}
      </div>
    </div>
  )
}
