import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Loader2 } from 'lucide-react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  icon?: ReactNode
  loading?: boolean
}

const VARIANT_STYLES: Record<Variant, string> = {
  primary: 'bg-accent text-white shadow-sm hover:bg-indigo-500 active:bg-indigo-600 border border-transparent',
  secondary: 'bg-surface-card text-slate-200 hover:bg-white/5 border border-surface-border',
  ghost: 'bg-transparent text-slate-300 hover:bg-white/5 border border-transparent',
  danger: 'bg-rose-600/90 text-white hover:bg-rose-600 border border-transparent',
}

const SIZE_STYLES: Record<Size, string> = {
  sm: 'px-2.5 py-1.5 text-xs',
  md: 'px-3.5 py-2 text-sm',
}

export function Button({
  variant = 'secondary', size = 'md', icon, loading, className = '', children, disabled, ...rest
}: ButtonProps) {
  return (
    <button
      className={`focus-ring inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50 ${VARIANT_STYLES[variant]} ${SIZE_STYLES[size]} ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : icon}
      {children}
    </button>
  )
}
