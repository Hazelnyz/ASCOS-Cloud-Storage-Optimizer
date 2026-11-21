import { createContext, useContext } from 'react'
import type { AuthUser } from '@/types'
import type { SignInResult } from '@/services/authService'

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated'

export interface AuthContextValue {
  status: AuthStatus
  user: AuthUser | null
  signIn: (email: string, password: string) => Promise<SignInResult>
  completeNewPassword: (newPassword: string) => Promise<void>
  signOut: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
