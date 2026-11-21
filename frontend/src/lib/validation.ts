// Deliberately permissive - this only catches obviously-malformed input for
// fast UI feedback. Cognito is the real validator; this never blocks a
// technically-valid address it happens to look unfamiliar with.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function isValidEmail(email: string): boolean {
  return EMAIL_RE.test(email.trim())
}
