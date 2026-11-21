import { PASSWORD_REQUIREMENTS } from '@/config/passwordPolicy'

const STRENGTH_STYLES = [
  { label: 'Weak', bar: 'bg-rose-500', text: 'text-rose-400' },
  { label: 'Weak', bar: 'bg-rose-500', text: 'text-rose-400' },
  { label: 'Fair', bar: 'bg-amber-500', text: 'text-amber-400' },
  { label: 'Good', bar: 'bg-amber-400', text: 'text-amber-300' },
  { label: 'Strong', bar: 'bg-emerald-500', text: 'text-emerald-400' },
  { label: 'Strong', bar: 'bg-emerald-500', text: 'text-emerald-400' },
]

/**
 * Compact strength meter: a thin segmented bar plus one line naming only what's
 * still missing (or confirming everything's met). Full requirement list stays
 * available to screen readers even though it's not printed out visually anymore.
 */
export function PasswordRequirements({ password }: { password: string }) {
  const results = PASSWORD_REQUIREMENTS.map((req) => ({ req, met: req.test(password) }))
  const metCount = results.filter((r) => r.met).length
  const missing = results.filter((r) => !r.met).map((r) => r.req.shortLabel)
  const empty = password.length === 0
  const style = STRENGTH_STYLES[metCount]

  return (
    <div>
      <p className="sr-only" aria-live="polite">
        {metCount} of {PASSWORD_REQUIREMENTS.length} password requirements met
        {missing.length > 0 ? `: still needs ${missing.join(', ')}` : ''}
      </p>
      <div className="flex gap-1" aria-hidden="true">
        {PASSWORD_REQUIREMENTS.map((req, i) => (
          <span
            key={req.id}
            className={`h-1 flex-1 rounded-full transition-colors ${
              empty ? 'bg-surface-border' : i < metCount ? style.bar : 'bg-surface-border'
            }`}
          />
        ))}
      </div>
      <p className={`mt-1 text-xs ${empty ? 'text-slate-500' : missing.length === 0 ? 'text-emerald-400' : style.text}`} aria-hidden="true">
        {empty
          ? 'At least 8 characters, with upper, lower, number and symbol.'
          : missing.length === 0
            ? 'Meets all requirements.'
            : `${style.label} · needs ${missing.join(', ')}`}
      </p>
    </div>
  )
}
