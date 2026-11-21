import { useRef, type ClipboardEvent, type KeyboardEvent } from 'react'

const LENGTH = 6

interface CodeInputProps {
  id: string
  value: string
  onChange: (code: string) => void
  disabled?: boolean
  groupLabel?: string
}

/** Six single-digit boxes that behave like one field: type-through, backspace-back, paste-fill. */
export function CodeInput({ id, value, onChange, disabled, groupLabel = 'Verification code' }: CodeInputProps) {
  const refs = useRef<Array<HTMLInputElement | null>>([])
  const digits = Array.from({ length: LENGTH }, (_, i) => value[i] ?? '')

  function handleChange(index: number, raw: string) {
    const clean = raw.replace(/\D/g, '')
    if (!clean) {
      const next = digits.slice()
      next[index] = ''
      onChange(next.join(''))
      return
    }
    const next = digits.slice()
    let i = index
    for (const c of clean) {
      if (i >= LENGTH) break
      next[i] = c
      i += 1
    }
    onChange(next.join('').slice(0, LENGTH))
    refs.current[Math.min(i, LENGTH - 1)]?.focus()
  }

  function handleKeyDown(index: number, e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Backspace' && !digits[index] && index > 0) refs.current[index - 1]?.focus()
    if (e.key === 'ArrowLeft' && index > 0) refs.current[index - 1]?.focus()
    if (e.key === 'ArrowRight' && index < LENGTH - 1) refs.current[index + 1]?.focus()
  }

  function handlePaste(e: ClipboardEvent<HTMLInputElement>) {
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, LENGTH)
    if (!pasted) return
    e.preventDefault()
    onChange(pasted)
    refs.current[Math.min(pasted.length, LENGTH - 1)]?.focus()
  }

  return (
    <div className="flex justify-between gap-2" role="group" aria-label={groupLabel}>
      {digits.map((d, i) => (
        <input
          key={i}
          id={i === 0 ? id : undefined}
          ref={(el) => {
            refs.current[i] = el
          }}
          inputMode="numeric"
          autoComplete={i === 0 ? 'one-time-code' : 'off'}
          maxLength={1}
          value={d}
          disabled={disabled}
          onChange={(e) => handleChange(i, e.target.value)}
          onKeyDown={(e) => handleKeyDown(i, e)}
          onPaste={handlePaste}
          aria-label={`Digit ${i + 1} of ${LENGTH}`}
          className="focus-ring h-11 w-full rounded-lg border border-surface-border bg-surface-raised text-center text-lg font-medium text-slate-100 disabled:opacity-50"
        />
      ))}
    </div>
  )
}
