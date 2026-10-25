import { useId, useRef, type KeyboardEvent, type ReactNode } from 'react'

export interface TabItem<K extends string> {
  key: K
  label: string
  /** Small text after the label, e.g. a count. */
  badge?: ReactNode
}

/** Accessible tab list: arrow keys move between tabs, Home/End jump. Panels are rendered by the caller. */
export function Tabs<K extends string>({
  items,
  value,
  onChange,
  label,
  variant = 'tabs',
}: {
  items: TabItem<K>[]
  value: K
  onChange: (key: K) => void
  label: string
  variant?: 'tabs' | 'pills'
}) {
  const id = useId()
  const refs = useRef<Record<string, HTMLButtonElement | null>>({})

  const onKey = (e: KeyboardEvent) => {
    const i = items.findIndex((t) => t.key === value)
    let next = -1
    if (e.key === 'ArrowRight') next = (i + 1) % items.length
    else if (e.key === 'ArrowLeft') next = (i - 1 + items.length) % items.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = items.length - 1
    if (next < 0) return
    e.preventDefault()
    onChange(items[next].key)
    refs.current[items[next].key]?.focus()
  }

  return (
    <div className={`tabs tabs-${variant}`} role="tablist" aria-label={label} onKeyDown={onKey}>
      {items.map((t) => (
        <button
          key={t.key}
          ref={(el) => {
            refs.current[t.key] = el
          }}
          id={`${id}-${t.key}`}
          role="tab"
          type="button"
          aria-selected={value === t.key}
          aria-controls={`${id}-panel`}
          tabIndex={value === t.key ? 0 : -1}
          className={`tab ${value === t.key ? 'on' : ''}`}
          onClick={() => onChange(t.key)}
        >
          {t.label}
          {t.badge != null && <span className="tab-badge">{t.badge}</span>}
        </button>
      ))}
    </div>
  )
}

export function TabPanel({ id, children }: { id?: string; children: ReactNode }) {
  return (
    <div role="tabpanel" id={id} className="tab-panel">
      {children}
    </div>
  )
}
