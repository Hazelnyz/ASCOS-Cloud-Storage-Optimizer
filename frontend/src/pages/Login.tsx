import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { Cloud } from 'lucide-react'
import { useAuth } from '@/context/authContext'
import { authService, mapAuthError } from '@/services/authService'
import { AuthError } from '@/services/errors'
import { Button } from '@/components/common/Button'
import { PasswordInput } from '@/components/common/PasswordInput'
import { PasswordRequirements } from '@/components/common/PasswordRequirements'
import { CodeInput } from '@/components/common/CodeInput'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { safeRedirectPath } from '@/lib/redirect'
import { isValidEmail } from '@/lib/validation'
import { isPasswordValid } from '@/config/passwordPolicy'

type View = 'sign_in' | 'new_password' | 'sign_up' | 'confirm_sign_up' | 'forgot_password' | 'confirm_forgot_password'

const RESEND_COOLDOWN_SECONDS = 30

const inputClass =
  'focus-ring w-full rounded-lg border border-surface-border bg-surface-raised px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500'

function Field({ label, htmlFor, hint, children }: { label: string; htmlFor: string; hint?: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={htmlFor} className="mb-1 block text-xs font-medium text-slate-400">{label}</label>
      {children}
      {hint && <p className="mt-1 text-xs text-rose-400">{hint}</p>}
    </div>
  )
}

/** Email field with light, non-blocking format feedback - shown only after the user leaves the field. */
function EmailField({
  id, label, value, onChange, autoFocus, disabled,
}: {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  autoFocus?: boolean
  disabled?: boolean
}) {
  const [touched, setTouched] = useState(false)
  const invalid = touched && value.length > 0 && !isValidEmail(value)
  return (
    <Field label={label} htmlFor={id} hint={invalid ? 'Enter a valid email address.' : undefined}>
      <input
        id={id}
        type="email"
        autoComplete="email"
        autoFocus={autoFocus}
        required
        disabled={disabled}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={() => setTouched(true)}
        aria-invalid={invalid}
        className={inputClass}
      />
    </Field>
  )
}

export function Login() {
  useDocumentTitle('Sign in')
  const { status, signIn, completeNewPassword } = useAuth()
  const location = useLocation()
  const from = safeRedirectPath((location.state as { from?: string } | null)?.from)

  const [view, setView] = useState<View>('sign_in')
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [confirmTouched, setConfirmTouched] = useState(false)
  const [newPassword, setNewPassword] = useState('')
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [resendCooldown, setResendCooldown] = useState(0)
  // Guards the *automatic* resend (not the visible manual resend button, which
  // already has its own cooldown via resendCooldown above). Ref, not state -
  // it never needs to render anything, just suppress a repeat Cognito call.
  const autoResendGuardRef = useRef<Map<string, number>>(new Map())

  // Ticks the resend cooldown down once a second while it's active.
  useEffect(() => {
    if (resendCooldown <= 0) return
    const timer = setInterval(() => setResendCooldown((s) => Math.max(0, s - 1)), 1000)
    return () => clearInterval(timer)
  }, [resendCooldown])

  if (status === 'authenticated') return <Navigate to={from} replace />

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(mapAuthError(err).message)
    } finally {
      setBusy(false)
    }
  }

  function resetSensitiveFields() {
    setPassword('')
    setConfirmPassword('')
    setConfirmTouched(false)
    setNewPassword('')
    setCode('')
  }

  function switchView(next: View) {
    setError(null)
    setNotice(null)
    resetSensitiveFields()
    setView(next)
  }

  // Scoped per (action, email) so, say, signing up as one address doesn't
  // block a genuinely-new auto-resend for a different one moments later.
  // Marked *before* the call fires, so even a failed attempt still guards the
  // window - a rapid-retry burst shouldn't turn into a rapid-retry-into-Cognito burst.
  function recentlyAutoResent(action: 'sign_up' | 'sign_in', forEmail: string): boolean {
    const key = `${action}:${forEmail.trim().toLowerCase()}`
    const last = autoResendGuardRef.current.get(key)
    const now = Date.now()
    if (last && now - last < RESEND_COOLDOWN_SECONDS * 1000) return true
    autoResendGuardRef.current.set(key, now)
    return false
  }

  function onSignIn(e: FormEvent) {
    e.preventDefault()
    void run(async () => {
      try {
        const result = await signIn(email, password)
        if (result.status === 'new_password_required') {
          setNotice('This account needs a new password before continuing.')
          resetSensitiveFields()
          setView('new_password')
        }
      } catch (err) {
        // A real, existing-but-unverified account - Cognito's own signal is
        // unambiguous here, so skip the manual step: send a fresh code (the
        // original one may be old or already used) and land straight on the
        // entry screen. Best-effort - a resend failure (e.g. rate limited)
        // still gets you to the right screen, just without a guaranteed-fresh code.
        if (err instanceof AuthError && err.code === 'user_not_confirmed') {
          resetSensitiveFields()
          setView('confirm_sign_up')
          if (recentlyAutoResent('sign_in', email)) {
            setNotice('This account still needs verifying. We emailed a code moments ago - check your inbox, or resend below once ready.')
            return
          }
          try {
            await authService.resendConfirmationCode(email)
            setNotice("This account still needs verifying - we've emailed a fresh code.")
            setResendCooldown(RESEND_COOLDOWN_SECONDS)
          } catch {
            setNotice('This account still needs verifying. Enter the code from your original email, or resend below.')
          }
          return
        }
        throw err
      }
    })
  }

  function onNewPassword(e: FormEvent) {
    e.preventDefault()
    void run(() => completeNewPassword(newPassword))
  }

  function onSignUp(e: FormEvent) {
    e.preventDefault()
    void run(async () => {
      try {
        await authService.signUp(email, password, displayName)
        setNotice('Account created. Check your email for a verification code.')
        resetSensitiveFields()
        setResendCooldown(RESEND_COOLDOWN_SECONDS)
        setView('confirm_sign_up')
      } catch (err) {
        if (err instanceof AuthError && err.code === 'user_exists') {
          if (recentlyAutoResent('sign_up', email)) {
            resetSensitiveFields()
            setView('confirm_sign_up')
            setNotice('We already emailed a code for this account moments ago - check your inbox, or wait to resend.')
            return
          }
          // Cognito's UsernameExistsException doesn't say *why* the account exists -
          // could be unconfirmed (recoverable) or fully confirmed (nothing to resend).
          // Rather than guess, just attempt the resend: if the account is genuinely
          // unconfirmed it succeeds and we can carry on; if it's already confirmed,
          // Cognito itself refuses it, and that refusal is our signal to fall through
          // to the normal "try signing in instead" message below.
          try {
            await authService.resendConfirmationCode(email)
            setNotice("That account was never verified - we've emailed a fresh code.")
            resetSensitiveFields()
            setResendCooldown(RESEND_COOLDOWN_SECONDS)
            setView('confirm_sign_up')
            return
          } catch {
            // Falls through to rethrow the original, already-correct sign-up error.
          }
        }
        throw err
      }
    })
  }

  function onConfirmSignUp(e: FormEvent) {
    e.preventDefault()
    void run(async () => {
      await authService.confirmSignUp(email, code)
      setNotice('Account verified. You can sign in now.')
      resetSensitiveFields()
      setView('sign_in')
    })
  }

  function onResendSignUpCode() {
    void run(async () => {
      await authService.resendConfirmationCode(email)
      setNotice('A new code has been emailed.')
      setResendCooldown(RESEND_COOLDOWN_SECONDS)
    })
  }

  function onForgotPassword(e: FormEvent) {
    e.preventDefault()
    void run(async () => {
      await authService.forgotPassword(email)
      setNotice('If that account exists, a reset code has been emailed to it.')
      setResendCooldown(RESEND_COOLDOWN_SECONDS)
      setView('confirm_forgot_password')
    })
  }

  function onResendResetCode() {
    void run(async () => {
      await authService.forgotPassword(email)
      setNotice('A new code has been emailed.')
      setResendCooldown(RESEND_COOLDOWN_SECONDS)
    })
  }

  function onConfirmForgotPassword(e: FormEvent) {
    e.preventDefault()
    void run(async () => {
      await authService.confirmForgotPassword(email, code, newPassword)
      setNotice('Password reset. You can sign in with your new password.')
      resetSensitiveFields()
      setView('sign_in')
    })
  }

  const signUpReady =
    isValidEmail(email) && isPasswordValid(password) && password.length > 0 && password === confirmPassword
  const passwordsMismatch = confirmTouched && confirmPassword.length > 0 && password !== confirmPassword

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-accent text-white">
            <Cloud className="h-5 w-5" aria-hidden="true" />
          </div>
          <h1 className="text-lg font-semibold text-slate-100">ASCOS</h1>
          <p className="text-xs text-slate-500">Adaptive Self-Learning Cloud Storage Optimization</p>
        </div>

        <div className="rounded-xl border border-surface-border bg-surface-card p-5 shadow-panel">
          {notice && (
            <p role="status" className="mb-3 rounded-md border border-emerald-500/25 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
              {notice}
            </p>
          )}
          {error && (
            <p role="alert" className="mb-3 rounded-md border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {error}
            </p>
          )}

          {/* Keyed by view so each step gets a fresh, deliberate fade-in rather than an instant swap. */}
          <div key={view} className="animate-fade-in">
            {view === 'sign_in' && (
              <form onSubmit={onSignIn} className="space-y-3" noValidate>
                <EmailField id="email" label="Email" value={email} onChange={setEmail} autoFocus disabled={busy} />
                <div>
                  <PasswordInput
                    id="password"
                    label="Password"
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    disabled={busy}
                  />
                  <div className="mt-1.5 text-right">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => switchView('forgot_password')}
                      className="focus-ring rounded text-xs font-medium text-accent hover:text-indigo-300 disabled:opacity-50"
                    >
                      Forgot password?
                    </button>
                  </div>
                </div>
                <Button type="submit" variant="primary" className="w-full" loading={busy}>
                  Sign in
                </Button>
                <p className="text-center text-xs text-slate-500">
                  No account?{' '}
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => switchView('sign_up')}
                    className="focus-ring rounded font-medium text-accent hover:text-indigo-300 disabled:opacity-50"
                  >
                    Create one
                  </button>
                </p>
                <p className="text-center text-xs text-slate-500">
                  Already have a verification code?{' '}
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => switchView('confirm_sign_up')}
                    className="focus-ring rounded font-medium text-accent hover:text-indigo-300 disabled:opacity-50"
                  >
                    Enter it
                  </button>
                </p>
              </form>
            )}

            {view === 'new_password' && (
              <form onSubmit={onNewPassword} className="space-y-3" noValidate>
                <p className="text-xs text-slate-500">Cognito requires a new password for this account before you can continue.</p>
                <PasswordInput
                  id="np"
                  label="New password"
                  autoComplete="new-password"
                  required
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  disabled={busy}
                />
                <PasswordRequirements password={newPassword} />
                <Button type="submit" variant="primary" className="w-full" loading={busy} disabled={!isPasswordValid(newPassword)}>
                  Set password and continue
                </Button>
              </form>
            )}

            {view === 'sign_up' && (
              <form onSubmit={onSignUp} className="space-y-3" noValidate>
                <Field label="Display name (optional)" htmlFor="su-name">
                  <input
                    id="su-name"
                    type="text"
                    autoComplete="nickname"
                    maxLength={50}
                    disabled={busy}
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="How should we address you?"
                    className={inputClass}
                  />
                </Field>
                <EmailField id="su-email" label="Email" value={email} onChange={setEmail} disabled={busy} />
                <PasswordInput
                  id="su-password"
                  label="Password"
                  autoComplete="new-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={busy}
                />
                <PasswordRequirements password={password} />
                <PasswordInput
                  id="su-confirm"
                  label="Confirm password"
                  autoComplete="new-password"
                  required
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  onBlur={() => setConfirmTouched(true)}
                  aria-invalid={passwordsMismatch}
                  disabled={busy}
                />
                {passwordsMismatch && <p className="text-xs text-rose-400">Passwords do not match.</p>}
                <Button type="submit" variant="primary" className="w-full" loading={busy} disabled={!signUpReady}>
                  Create account
                </Button>
                <button type="button" disabled={busy} onClick={() => switchView('sign_in')} className="focus-ring block w-full text-center text-xs text-slate-500 hover:text-slate-300 disabled:opacity-50">
                  Back to sign in
                </button>
              </form>
            )}

            {view === 'confirm_sign_up' && (
              <form onSubmit={onConfirmSignUp} className="space-y-3" noValidate>
                <div>
                  <p className="mb-1 text-xs font-medium text-slate-400">Verification code</p>
                  <p className="mb-2 text-xs text-slate-500">Sent to {email || 'your email'}.</p>
                  <CodeInput id="code1" value={code} onChange={setCode} disabled={busy} />
                </div>
                <Button type="submit" variant="primary" className="w-full" loading={busy} disabled={code.length !== 6}>
                  Verify account
                </Button>
                <button
                  type="button"
                  disabled={busy || resendCooldown > 0}
                  onClick={onResendSignUpCode}
                  className="focus-ring block w-full text-center text-xs text-slate-500 hover:text-slate-300 disabled:opacity-50"
                >
                  {resendCooldown > 0 ? `Resend code (${resendCooldown}s)` : 'Resend code'}
                </button>
              </form>
            )}

            {view === 'forgot_password' && (
              <form onSubmit={onForgotPassword} className="space-y-3" noValidate>
                <EmailField id="fp-email" label="Email" value={email} onChange={setEmail} autoFocus disabled={busy} />
                <Button type="submit" variant="primary" className="w-full" loading={busy}>
                  Send reset code
                </Button>
                <button type="button" disabled={busy} onClick={() => switchView('sign_in')} className="focus-ring block w-full text-center text-xs text-slate-500 hover:text-slate-300 disabled:opacity-50">
                  Back to sign in
                </button>
              </form>
            )}

            {view === 'confirm_forgot_password' && (
              <form onSubmit={onConfirmForgotPassword} className="space-y-3" noValidate>
                <div>
                  <p className="mb-1 text-xs font-medium text-slate-400">Reset code</p>
                  <p className="mb-2 text-xs text-slate-500">Sent to {email || 'your email'}.</p>
                  <CodeInput id="code2" value={code} onChange={setCode} disabled={busy} />
                </div>
                <PasswordInput
                  id="np2"
                  label="New password"
                  autoComplete="new-password"
                  required
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  disabled={busy}
                />
                <PasswordRequirements password={newPassword} />
                <Button
                  type="submit"
                  variant="primary"
                  className="w-full"
                  loading={busy}
                  disabled={code.length !== 6 || !isPasswordValid(newPassword)}
                >
                  Reset password
                </Button>
                <button
                  type="button"
                  disabled={busy || resendCooldown > 0}
                  onClick={onResendResetCode}
                  className="focus-ring block w-full text-center text-xs text-slate-500 hover:text-slate-300 disabled:opacity-50"
                >
                  {resendCooldown > 0 ? `Resend code (${resendCooldown}s)` : 'Resend code'}
                </button>
              </form>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
