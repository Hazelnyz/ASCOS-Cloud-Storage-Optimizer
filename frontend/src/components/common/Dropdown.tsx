import { Fragment, useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { MoreVertical } from 'lucide-react'

export interface DropdownItem {
  label: string
  onSelect: () => void
  icon?: ReactNode
  danger?: boolean
  disabled?: boolean
  /** Shown as the item's tooltip/description (e.g. why it is disabled). */
  hint?: string
}

interface DropdownProps {
  items: DropdownItem[]
  trigger?: ReactNode
  /** Accessible name of the trigger button. */
  label: string
}

export function Dropdown({ items, trigger, label }: DropdownProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([])
  const menuId = useId()

  const enabledIndexes = items.map((it, i) => (it.disabled ? -1 : i)).filter((i) => i >= 0)

  useEffect(() => {
    if (!open) return
    const onMouseDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [open])

  function focusItem(index: number | undefined) {
    if (index !== undefined) itemRefs.current[index]?.focus()
  }

  function openAndFocus(which: 'first' | 'last') {
    setOpen(true)
    // Wait for the menu to render before moving focus.
    setTimeout(() => focusItem(which === 'first' ? enabledIndexes[0] : enabledIndexes[enabledIndexes.length - 1]), 0)
  }

  function onTriggerKeyDown(e: KeyboardEvent<HTMLButtonElement>) {
    if (e.key === 'ArrowDown') { e.preventDefault(); openAndFocus('first') }
    else if (e.key === 'ArrowUp') { e.preventDefault(); openAndFocus('last') }
  }

  function onMenuKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const current = itemRefs.current.findIndex((el) => el === document.activeElement)
    const pos = enabledIndexes.indexOf(current)
    if (e.key === 'ArrowDown') { e.preventDefault(); focusItem(enabledIndexes[(pos + 1) % enabledIndexes.length]) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); focusItem(enabledIndexes[(pos - 1 + enabledIndexes.length) % enabledIndexes.length]) }
    else if (e.key === 'Home') { e.preventDefault(); focusItem(enabledIndexes[0]) }
    else if (e.key === 'End') { e.preventDefault(); focusItem(enabledIndexes[enabledIndexes.length - 1]) }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setOpen(false); triggerRef.current?.focus() }
    else if (e.key === 'Tab') { setOpen(false) }
  }

  return (
    <div className="relative" ref={rootRef}>
      <button
        ref={triggerRef}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={onTriggerKeyDown}
        className="focus-ring rounded-md p-1.5 text-slate-400 hover:bg-white/5 hover:text-slate-200"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={label}
      >
        {trigger ?? <MoreVertical className="h-4 w-4" aria-hidden="true" />}
      </button>
      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label={label}
          onKeyDown={onMenuKeyDown}
          className="absolute right-0 z-20 mt-1.5 w-56 overflow-hidden rounded-xl border border-surface-border bg-surface-raised py-1.5 shadow-xl shadow-black/40"
        >
          {items.map((item, i) => (
            <Fragment key={item.label}>
            {item.danger && i > 0 && !items[i - 1].danger && <div role="separator" className="my-1 h-px bg-surface-border" />}
            <button
              ref={(el) => { itemRefs.current[i] = el }}
              role="menuitem"
              disabled={item.disabled}
              title={item.hint}
              tabIndex={-1}
              onClick={() => { setOpen(false); triggerRef.current?.focus(); item.onSelect() }}
              className={`focus-ring flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-50 ${item.danger ? 'text-rose-400' : 'text-slate-200'}`}
            >
              {item.icon}
              {item.label}
            </button>
            </Fragment>
          ))}
        </div>
      )}
    </div>
  )
}
