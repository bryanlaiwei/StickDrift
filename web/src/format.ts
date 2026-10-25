const dateTimeFmt = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
})

export const formatDateTime = (iso: string) => dateTimeFmt.format(new Date(iso))

const dateFmt = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' })

/** Short "Oct 17" style label for chart axes. */
const formatDate = (iso: string) => dateFmt.format(new Date(iso))

const shortFmt = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })

/** Axis labels for visits: the date, or date and time when several fall on the same day. */
export function visitLabels(isoTimes: string[]): string[] {
  const dates = isoTimes.map(formatDate)
  return new Set(dates).size === dates.length ? dates : isoTimes.map((t) => shortFmt.format(new Date(t)))
}

export const pct = (v: number | null | undefined, digits = 0) => (v == null ? '—' : `${(v * 100).toFixed(digits)}%`)
export const secs = (v: number | null | undefined) => (v == null ? '—' : `${v.toFixed(2)} s`)
