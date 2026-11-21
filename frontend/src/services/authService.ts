// Amazon Cognito authentication (SRP) via amazon-cognito-identity-js.
//
// The App Client is SRP-only, so sign-in cannot be a plain credentials POST;
// the SDK performs the SRP handshake. Components never import the SDK - they go
// through this interface (and AuthContext).
//
// Tokens are held by the SDK in browser storage (localStorage). That is the
// SDK's design; the mitigation is a strict Content-Security-Policy on the
// hosted app (see docs/AMPLIFY_READINESS.md) and never rendering untrusted HTML.

import {
  AuthenticationDetails, CognitoUser, CognitoUserAttribute, CognitoUserPool,
  type CognitoUserSession,
} from 'amazon-cognito-identity-js'
import { getConfig } from '@/config/env'
import { AuthError, type AuthErrorCode } from './errors'
import type { AuthUser } from '@/types'

export type SignInResult =
  | { status: 'signed_in'; user: AuthUser }
  | { status: 'new_password_required' }

export interface AuthService {
  getCurrentUser(): Promise<AuthUser | null>
  signIn(email: string, password: string): Promise<SignInResult>
  completeNewPassword(newPassword: string): Promise<AuthUser>
  signUp(email: string, password: string, displayName?: string): Promise<void>
  confirmSignUp(email: string, code: string): Promise<void>
  resendConfirmationCode(email: string): Promise<void>
  forgotPassword(email: string): Promise<void>
  confirmForgotPassword(email: string, code: string, newPassword: string): Promise<void>
  signOut(): Promise<void>
  /** A currently valid ACCESS token (the SDK refreshes an expired one transparently). */
  getAccessToken(): Promise<string>
  /** Force a refresh using the refresh token. */
  refreshSession(): Promise<void>
}

interface CognitoLikeError { code?: string; name?: string; message?: string }

/** Which screen/action triggered the Cognito call - lets one raw exception get a different, contextually-correct message. */
export type AuthAction = 'sign_in' | 'sign_up' | 'confirm_sign_up' | 'new_password' | 'forgot_password' | 'confirm_forgot_password'

const AUTH_MESSAGES: Record<AuthErrorCode, string> = {
  invalid_credentials: 'Incorrect email or password.',
  user_not_confirmed: 'This account has not been verified yet. Enter the verification code we emailed you.',
  password_reset_required: 'A password reset is required for this account. Use "Forgot password?".',
  invalid_password: 'That password does not meet the password requirements.',
  invalid_code: 'That verification code is not correct.',
  expired_code: 'That verification code has expired. Request a new one.',
  user_exists: 'An account with this email already exists.',
  rate_limited: 'Too many attempts. Please wait a while before trying again.',
  not_permitted: 'This action is not enabled for this deployment.',
  unsupported_challenge: 'This account requires a sign-in step that this app does not support yet.',
  no_session: 'You are not signed in.',
  network: 'Could not reach the sign-in service. Check your connection and try again.',
  unknown: 'Something went wrong. Please try again.',
}

// The user pool has prevent_user_existence_errors = ENABLED (cognito.tf), which makes
// Cognito mask "this email already exists" behind the same generic NotAuthorizedException
// used for a plain wrong-password sign-in - deliberately, to stop the form being used to
// probe which emails are registered. That's correct behaviour from Cognito, but it means
// AUTH_MESSAGES.invalid_credentials ("Incorrect email or password") is actively misleading
// on a screen where nothing has been created yet to have a "wrong password" against.
// Override the *wording* per action without changing what actually happened.
const ACTION_OVERRIDES: Partial<Record<AuthAction, Partial<Record<AuthErrorCode, string>>>> = {
  sign_up: {
    invalid_credentials:
      "We couldn't create that account. If you already have one, try signing in, or use \"Forgot password?\" instead.",
  },
}

export function mapAuthError(err: unknown, action?: AuthAction): AuthError {
  if (err instanceof AuthError) return err
  const e = (err ?? {}) as CognitoLikeError
  const name = e.code ?? e.name ?? ''
  let code: AuthErrorCode
  switch (name) {
    // UserNotFound is folded into invalid_credentials to avoid account enumeration.
    case 'NotAuthorizedException': code = 'invalid_credentials'; break
    case 'UserNotFoundException': code = 'invalid_credentials'; break
    case 'UserNotConfirmedException': code = 'user_not_confirmed'; break
    case 'PasswordResetRequiredException': code = 'password_reset_required'; break
    case 'InvalidPasswordException': code = 'invalid_password'; break
    case 'CodeMismatchException': code = 'invalid_code'; break
    case 'ExpiredCodeException': code = 'expired_code'; break
    case 'UsernameExistsException': code = 'user_exists'; break
    case 'LimitExceededException':
    case 'TooManyRequestsException':
    case 'TooManyFailedAttemptsException': code = 'rate_limited'; break
    case 'InvalidParameterException':
    case 'InvalidLambdaResponseException': code = 'not_permitted'; break
    case 'NetworkError': code = 'network'; break
    default: code = 'unknown'
  }
  if (import.meta.env.DEV) {
    // Dev-only: the exact raw Cognito exception behind the friendly message, so a
    // confusing message can be traced to its real cause instead of guessed at.
    // eslint-disable-next-line no-console -- deliberate, dev-only diagnostic
    console.warn(`[auth:${action ?? 'unknown'}]`, name, e.message)
  }
  const override = action ? ACTION_OVERRIDES[action]?.[code] : undefined
  // InvalidPassword messages from Cognito describe the policy and are safe/useful.
  const message = override ?? (code === 'invalid_password' && e.message ? e.message : AUTH_MESSAGES[code])
  return new AuthError(code, message)
}

function userFromSession(session: CognitoUserSession): AuthUser {
  const p = session.getIdToken().payload as Record<string, unknown>
  const displayName = p['custom:display_name']
  return {
    userId: String(p.sub ?? ''),
    email: typeof p.email === 'string' ? p.email : '',
    displayName: typeof displayName === 'string' && displayName ? displayName : null,
  }
}

export function createCognitoAuthService(): AuthService {
  const cfg = getConfig()
  const pool = new CognitoUserPool({ UserPoolId: cfg.cognitoUserPoolId, ClientId: cfg.cognitoClientId })
  // Holds the user object between "new password required" and its completion.
  let pendingChallengeUser: CognitoUser | null = null

  const userFor = (email: string) => new CognitoUser({ Username: email.trim(), Pool: pool })

  function getSession(user: CognitoUser): Promise<CognitoUserSession> {
    return new Promise((resolve, reject) => {
      user.getSession((err: unknown, session: CognitoUserSession | null) => {
        if (err || !session || !session.isValid()) reject(mapAuthError(err ?? new AuthError('no_session', AUTH_MESSAGES.no_session)))
        else resolve(session)
      })
    })
  }

  return {
    async getCurrentUser() {
      const user = pool.getCurrentUser()
      if (!user) return null
      try {
        return userFromSession(await getSession(user))
      } catch {
        return null
      }
    },

    signIn(email, password) {
      return new Promise<SignInResult>((resolve, reject) => {
        const user = userFor(email)
        user.authenticateUser(new AuthenticationDetails({ Username: email.trim(), Password: password }), {
          onSuccess: (session) => {
            pendingChallengeUser = null
            resolve({ status: 'signed_in', user: userFromSession(session) })
          },
          onFailure: (err) => reject(mapAuthError(err, 'sign_in')),
          newPasswordRequired: () => {
            pendingChallengeUser = user
            resolve({ status: 'new_password_required' })
          },
          // MFA is not enabled on the pool yet; if it ever is, fail truthfully.
          mfaRequired: () => reject(new AuthError('unsupported_challenge', AUTH_MESSAGES.unsupported_challenge)),
          totpRequired: () => reject(new AuthError('unsupported_challenge', AUTH_MESSAGES.unsupported_challenge)),
          customChallenge: () => reject(new AuthError('unsupported_challenge', AUTH_MESSAGES.unsupported_challenge)),
          mfaSetup: () => reject(new AuthError('unsupported_challenge', AUTH_MESSAGES.unsupported_challenge)),
          selectMFAType: () => reject(new AuthError('unsupported_challenge', AUTH_MESSAGES.unsupported_challenge)),
        })
      })
    },

    completeNewPassword(newPassword) {
      return new Promise<AuthUser>((resolve, reject) => {
        const user = pendingChallengeUser
        if (!user) {
          reject(new AuthError('no_session', AUTH_MESSAGES.no_session))
          return
        }
        user.completeNewPasswordChallenge(newPassword, {}, {
          onSuccess: (session) => {
            pendingChallengeUser = null
            resolve(userFromSession(session))
          },
          onFailure: (err) => reject(mapAuthError(err, 'new_password')),
        })
      })
    },

    signUp(email, password, displayName) {
      return new Promise<void>((resolve, reject) => {
        const attrs = [new CognitoUserAttribute({ Name: 'email', Value: email.trim() })]
        // Optional per cognito.tf's schema block - only sent if the user actually filled it in.
        const trimmedName = displayName?.trim()
        if (trimmedName) attrs.push(new CognitoUserAttribute({ Name: 'custom:display_name', Value: trimmedName }))
        pool.signUp(email.trim(), password, attrs, [], (err) => (err ? reject(mapAuthError(err, 'sign_up')) : resolve()))
      })
    },

    confirmSignUp(email, code) {
      return new Promise<void>((resolve, reject) => {
        userFor(email).confirmRegistration(code.trim(), true, (err) => (err ? reject(mapAuthError(err, 'confirm_sign_up')) : resolve()))
      })
    },

    resendConfirmationCode(email) {
      return new Promise<void>((resolve, reject) => {
        userFor(email).resendConfirmationCode((err) => (err ? reject(mapAuthError(err, 'confirm_sign_up')) : resolve()))
      })
    },

    forgotPassword(email) {
      return new Promise<void>((resolve, reject) => {
        userFor(email).forgotPassword({
          onSuccess: () => resolve(),
          onFailure: (err) => reject(mapAuthError(err, 'forgot_password')),
        })
      })
    },

    confirmForgotPassword(email, code, newPassword) {
      return new Promise<void>((resolve, reject) => {
        userFor(email).confirmPassword(code.trim(), newPassword, {
          onSuccess: () => resolve(),
          onFailure: (err) => reject(mapAuthError(err, 'confirm_forgot_password')),
        })
      })
    },

    async signOut() {
      pendingChallengeUser = null
      pool.getCurrentUser()?.signOut()
    },

    async getAccessToken() {
      const user = pool.getCurrentUser()
      if (!user) throw new AuthError('no_session', AUTH_MESSAGES.no_session)
      return (await getSession(user)).getAccessToken().getJwtToken()
    },

    async refreshSession() {
      const user = pool.getCurrentUser()
      if (!user) throw new AuthError('no_session', AUTH_MESSAGES.no_session)
      const session = await getSession(user)
      await new Promise<void>((resolve, reject) => {
        user.refreshSession(session.getRefreshToken(), (err) => (err ? reject(mapAuthError(err)) : resolve()))
      })
    },
  }
}

let instance: AuthService | null = null

/** Lazily created so a configuration error is reported by the UI, not at import time. */
export const authService: AuthService = {
  getCurrentUser: () => svc().getCurrentUser(),
  signIn: (e, p) => svc().signIn(e, p),
  completeNewPassword: (p) => svc().completeNewPassword(p),
  signUp: (e, p, n) => svc().signUp(e, p, n),
  confirmSignUp: (e, c) => svc().confirmSignUp(e, c),
  resendConfirmationCode: (e) => svc().resendConfirmationCode(e),
  forgotPassword: (e) => svc().forgotPassword(e),
  confirmForgotPassword: (e, c, p) => svc().confirmForgotPassword(e, c, p),
  signOut: () => svc().signOut(),
  getAccessToken: () => svc().getAccessToken(),
  refreshSession: () => svc().refreshSession(),
}

function svc(): AuthService {
  if (!instance) instance = createCognitoAuthService()
  return instance
}
