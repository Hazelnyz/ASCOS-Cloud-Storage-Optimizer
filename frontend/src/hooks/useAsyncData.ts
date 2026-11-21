import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '@/services/errors'

interface State<T> {
  data: T | null
  error: unknown
  loading: boolean
}

/**
 * Loads data with cancellation: unmounting (or reloading) aborts the in-flight
 * request and stale responses can never overwrite newer state. Existing data is
 * kept while a reload is in flight (no flash back to a blank skeleton).
 */
export function useAsyncData<T>(loader: (signal: AbortSignal) => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true })
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setState((s) => ({ ...s, loading: true, error: null }))
    loader(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ data, error: null, loading: false })
      })
      .catch((error) => {
        if (controller.signal.aborted) return
        if (error instanceof ApiError && error.kind === 'aborted') return
        setState((s) => ({ ...s, error, loading: false }))
      })
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce, ...deps])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  const mutate = useCallback((fn: (current: T) => T) => {
    setState((s) => (s.data === null ? s : { ...s, data: fn(s.data) }))
  }, [])

  return { ...state, reload, mutate }
}
