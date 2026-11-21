import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'

interface State { failed: boolean }

/** Catches render-time exceptions so a single bug never white-screens the app. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Log for developers only; nothing is shown to the user beyond a generic message.
    console.error('Unhandled UI error', error, info.componentStack)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div role="alert" className="flex min-h-screen flex-col items-center justify-center gap-3 bg-surface px-4 text-center">
        <AlertTriangle className="h-8 w-8 text-rose-400" aria-hidden="true" />
        <h1 className="text-lg font-semibold text-slate-100">Something went wrong</h1>
        <p className="max-w-sm text-sm text-slate-400">The page hit an unexpected problem. Reloading usually fixes it.</p>
        <button
          onClick={() => window.location.reload()}
          className="focus-ring rounded-lg border border-surface-border bg-surface-card px-3.5 py-2 text-sm font-medium text-slate-200 hover:bg-white/5"
        >
          Reload the app
        </button>
      </div>
    )
  }
}
