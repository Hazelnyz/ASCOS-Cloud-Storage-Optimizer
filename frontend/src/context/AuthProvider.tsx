import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { authService } from '@/services/authService'
import { onSessionExpired } from '@/services/authEvents'
import { clearMetadataCache } from '@/hooks/useFileMetadata'
import type { AuthUser } from '@/types'
import { AuthContext, type AuthStatus } from './authContext'

interface State { status: AuthStatus; user: AuthUser | null }

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: 'loading', user: null })

  // Restore a persisted session (the SDK keeps tokens across reloads).
  useEffect(() => {
    let cancelled = false
    authService
      .getCurrentUser()
      .then((user) => {
        if (!cancelled) setState(user ? { status: 'authenticated', user } : { status: 'unauthenticated', user: null })
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'unauthenticated', user: null })
      })
    return () => {
      cancelled = true
    }
  }, [])

  // The HTTP layer reports an unrecoverable 401 (refresh already tried once).
  useEffect(
    () =>
      onSessionExpired(() => {
        void authService.signOut()
        clearMetadataCache()
        setState({ status: 'unauthenticated', user: null })
      }),
    [],
  )

  const signIn = useCallback(async (email: string, password: string) => {
    const result = await authService.signIn(email, password)
    if (result.status === 'signed_in') setState({ status: 'authenticated', user: result.user })
    return result
  }, [])

  const completeNewPassword = useCallback(async (newPassword: string) => {
    const user = await authService.completeNewPassword(newPassword)
    setState({ status: 'authenticated', user })
  }, [])

  const signOut = useCallback(async () => {
    await authService.signOut()
    clearMetadataCache()
    setState({ status: 'unauthenticated', user: null })
  }, [])

  const value = useMemo(
    () => ({ ...state, signIn, completeNewPassword, signOut }),
    [state, signIn, completeNewPassword, signOut],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
