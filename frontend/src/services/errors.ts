// One error type for everything that can go wrong talking to the backend.
// `message` is ALWAYS safe to show a user: it never contains raw backend text,
// URLs, tokens or AWS internals. Raw details stay out of the UI by design.

export type ApiErrorKind =
  | 'unauthorized'
  | 'forbidden'
  | 'not_found'
  | 'conflict'
  | 'rate_limited'
  | 'validation'
  | 'server'
  | 'network'
  | 'timeout'
  | 'malformed'
  | 'aborted'
  | 'too_large'
  | 'link_expired'
  | 'unsupported'

const MESSAGES: Record<ApiErrorKind, string> = {
  unauthorized: 'Your session has expired. Please sign in again.',
  forbidden: 'You do not have permission to do that.',
  not_found: 'That file could not be found. It may have been deleted.',
  conflict: 'That action conflicts with the current state. Refresh and try again.',
  rate_limited: 'Too many requests. Please wait a moment and try again.',
  validation: 'The request was rejected. Please check the input and try again.',
  server: 'The service had a problem completing that request. Please try again.',
  network: 'Could not reach the service. Check your connection and try again.',
  timeout: 'The request took too long. Please try again.',
  malformed: 'The service returned an unexpected response. Please try again later.',
  aborted: 'The request was cancelled.',
  too_large: 'That file is too large to upload from the browser.',
  link_expired: 'The upload link expired or was rejected. Retry to get a fresh link.',
  unsupported: 'This action is not supported by the current backend version.',
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind
  readonly status: number | null
  constructor(kind: ApiErrorKind, status: number | null = null, message?: string) {
    super(message ?? MESSAGES[kind])
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
  }
}

export type AuthErrorCode =
  | 'invalid_credentials'
  | 'user_not_confirmed'
  | 'password_reset_required'
  | 'invalid_password'
  | 'invalid_code'
  | 'expired_code'
  | 'user_exists'
  | 'rate_limited'
  | 'not_permitted'
  | 'unsupported_challenge'
  | 'no_session'
  | 'network'
  | 'unknown'

export class AuthError extends Error {
  readonly code: AuthErrorCode
  constructor(code: AuthErrorCode, message: string) {
    super(message)
    this.name = 'AuthError'
    this.code = code
  }
}

/** Convert anything thrown into a message that is safe to display. */
export function toUserMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof AuthError) return error.message
  return 'Something went wrong. Please try again.'
}
