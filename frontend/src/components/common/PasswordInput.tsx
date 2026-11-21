import { useState, type InputHTMLAttributes } from 'react'
import { Eye, EyeOff } from 'lucide-react'

interface PasswordInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label: string
}

const inputClass =
  'focus-ring w-full rounded-lg border border-surface-border bg-surface-raised px-3 py-2 pr-10 text-sm text-slate-100 placeholder:text-slate-500'

/** A password field with a show/hide toggle. Visibility is per-field, local state only. */
export function PasswordInput({ id, label, className = '', ...rest }: PasswordInputProps) {
  const [visible, setVisible] = useState(false)

  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-slate-400">
        {label}
      </label>
      <div className="relative">
        <input id={id} type={visible ? 'text' : 'password'} className={`${inputClass} ${className}`} {...rest} />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          className="focus-ring absolute inset-y-0 right-0 grid w-9 place-items-center text-slate-500 hover:text-slate-300"
          aria-label={visible ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
          aria-pressed={visible}
        >
          {visible ? <EyeOff className="h-4 w-4" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}
        </button>
      </div>
    </div>
  )
}
