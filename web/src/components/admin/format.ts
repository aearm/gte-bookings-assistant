// Small text helpers shared by the admin pages.

/** "1 cube", "3 cubes" */
export function plural(n: number, word: string, many = `${word}s`): string {
  return `${n.toLocaleString('en-GB')} ${n === 1 ? word : many}`
}

/** $1.23 (or $0.012 for small amounts when digits = 3) */
export function money(value: number | null | undefined, digits = 2): string {
  const v = Number(value ?? 0)
  return `$${v.toLocaleString('en-GB', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`
}

export function percent(value: number | null | undefined): string {
  return value == null || Number.isNaN(value) ? '–' : `${Math.round(value * 100)}%`
}

export function secondsText(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '–'
  return value >= 10 ? `${Math.round(value)} s` : `${value.toFixed(1)} s`
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-10-16T14:05:09" → "16 Oct 14:05" (the server's local time, shown as written) */
export function whenText(iso: string | null | undefined, withYear = false): string {
  if (!iso) return ''
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(iso)
  if (!m) return iso
  const day = `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? m[2]}${withYear ? ` ${m[1]}` : ''}`
  return m[4] ? `${day} ${m[4]}:${m[5]}` : day
}

/** Short name for menus, as cubes.label(): 'Company - Bookings' → 'Bookings' */
export function shortCubeLabel(name: string): string {
  const cut = name.indexOf(' - ')
  return cut >= 0 ? name.slice(cut + 3) : name
}
