// Mirrors terraform/cognito.tf -> aws_cognito_user_pool.main.password_policy
// (minimum_length = 8, require_lowercase/uppercase/numbers/symbols = true).
//
// Cognito is the source of truth and enforces this policy server-side no
// matter what this file says - these constants only drive the *live*
// requirements checklist shown while someone is typing a password, so the
// UI doesn't guess at rules it can't actually see. Cognito's password
// policy isn't exposed by any public, unauthenticated API, so this has to
// be a maintained constant rather than something fetched at runtime.
//
// If cognito.tf's password_policy block ever changes, update this file to
// match in the same change.

export const PASSWORD_MIN_LENGTH = 8

export interface PasswordRequirement {
  id: string
  label: string
  /** Short form for compact contexts (a "still missing" line), e.g. "8+ characters" -> "length". */
  shortLabel: string
  test: (password: string) => boolean
}

export const PASSWORD_REQUIREMENTS: PasswordRequirement[] = [
  { id: 'length', label: `${PASSWORD_MIN_LENGTH}+ characters`, shortLabel: `${PASSWORD_MIN_LENGTH}+ characters`, test: (p) => p.length >= PASSWORD_MIN_LENGTH },
  { id: 'lower', label: 'A lowercase letter', shortLabel: 'lowercase', test: (p) => /[a-z]/.test(p) },
  { id: 'upper', label: 'An uppercase letter', shortLabel: 'uppercase', test: (p) => /[A-Z]/.test(p) },
  { id: 'number', label: 'A number', shortLabel: 'a number', test: (p) => /[0-9]/.test(p) },
  // Cognito's default allowed-symbol set is broad; this is a permissive UI hint,
  // not the enforcement - Cognito itself is what actually accepts or rejects it.
  { id: 'symbol', label: 'A symbol (e.g. ! @ # $ %)', shortLabel: 'a symbol', test: (p) => /[^A-Za-z0-9]/.test(p) },
]

export function isPasswordValid(password: string): boolean {
  return PASSWORD_REQUIREMENTS.every((r) => r.test(password))
}
