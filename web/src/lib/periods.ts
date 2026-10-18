// Dashboard periods in the browser: the quick choices, ISO week numbers, labels and comparisons. A
// port of periods.py (the server's reference), so the picker can show dates at once.
// Dates are ISO strings 'YYYY-MM-DD'; inside, days since 1 Jan 1970 (UTC) so adding days is plain
// arithmetic. Every period is [start, end) with end exclusive: the day after the last day.

export const PRESETS = ['Today', 'Yesterday', 'This week', 'Last week', 'Last 7 days', 'Last 30 days', 'This month',
  'Last month', 'This quarter', 'Last quarter', 'This year', 'Last year', 'Last 12 months'] as const
export const DEFAULT_PRESET = 'Last 7 days'

export const COMPARE_MODES = {
  none: 'No comparison', previous: 'Previous period', last_year: 'Same period last year', custom: 'Other dates',
} as const
export type CompareMode = keyof typeof COMPARE_MODES
export const DEFAULT_COMPARE: CompareMode = 'previous'

export const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
  'October', 'November', 'December']
export const SHORT_MONTHS = MONTHS.map((m) => m.slice(0, 3))

const DAY_MS = 86_400_000

export const isPreset = (name: string | null | undefined): boolean => !!name && (PRESETS as readonly string[]).includes(name)
export const isCompareMode = (mode: string | null | undefined): mode is CompareMode => !!mode && mode in COMPARE_MODES

/** Day number of an ISO date. */
export function toDay(iso: string): number {
  const [y, m, d] = iso.split('-').map(Number)
  return Date.UTC(y, m - 1, d) / DAY_MS
}
export const toIso = (day: number): string => new Date(day * DAY_MS).toISOString().slice(0, 10)
export const isIsoDate = (text: string | null | undefined): text is string =>
  !!text && /^\d{4}-\d{2}-\d{2}$/.test(text) && toIso(toDay(text)) === text

/** [year, month 1-12, day] of a day number. */
export function ymd(day: number): [number, number, number] {
  const d = new Date(day * DAY_MS)
  return [d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate()]
}
/** Day number of a date (month 1-12; months beyond 12 or below 1 roll into the next / last years). */
export const fromYmd = (y: number, m: number, d: number): number => Date.UTC(y, m - 1, d) / DAY_MS
export const weekday = (day: number): number => (new Date(day * DAY_MS).getUTCDay() + 6) % 7 // Monday = 0
export const daysInMonth = (y: number, m: number): number => fromYmd(y, m + 1, 1) - fromYmd(y, m, 1)

/** Today in the browser's time zone, as an ISO date. */
export function todayIso(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

// ---------------------------------------------------------------- ISO weeks --
// Weeks start on Monday; week 1 is the week with the year's first Thursday (29 Dec 2025 is in week 1
// of 2026, and 2026 has 53 weeks).

export function isoWeek(day: number): { year: number; week: number } {
  const thursday = day - weekday(day) + 3
  const year = ymd(thursday)[0]
  return { year, week: Math.floor((thursday - fromYmd(year, 1, 1)) / 7) + 1 }
}
/** Day number of the Monday of an ISO week. */
export function weekMonday(year: number, week: number): number {
  const jan4 = fromYmd(year, 1, 4)
  return jan4 - weekday(jan4) + (week - 1) * 7
}
/** 52 or 53: 28 December is always in the year's last week. */
export const weeksInYear = (year: number): number => isoWeek(fromYmd(year, 12, 28)).week

/** Monday of the first week to the Monday after the last (weeks clamped to the year's weeks). */
export function weekRange(year: number, firstWeek: number, lastWeek = firstWeek): [number, number] {
  const top = weeksInYear(year)
  const clamp = (w: number) => Math.max(1, Math.min(w, top))
  const [a, b] = [clamp(Math.min(firstWeek, lastWeek)), clamp(Math.max(firstWeek, lastWeek))]
  return [weekMonday(year, a), weekMonday(year, b) + 7]
}

/** 'week 41', 'weeks 1–42' or 'weeks 52 (2025) – 3 (2026)' (end exclusive). */
export function weeksOf(start: number, end: number): string {
  const w1 = isoWeek(start), w2 = isoWeek(end - 1)
  if (w1.year === w2.year && w1.week === w2.week) return `week ${w1.week}`
  if (w1.year === w2.year) return `weeks ${w1.week}–${w2.week}`
  return `weeks ${w1.week} (${w1.year}) – ${w2.week} (${w2.year})`
}

// ---------------------------------------------------------------- labels --

/** '1 Jan – 13 Oct 2026', '5 Oct 2026', '29 Dec 2025 – 4 Jan 2026' (end exclusive). */
export function datesText(start: number, end: number): string {
  const last = end - 1
  const [y1, m1, d1] = ymd(start), [y2, m2, d2] = ymd(last)
  if (start === last) return `${d1} ${SHORT_MONTHS[m1 - 1]} ${y1}`
  return `${d1} ${SHORT_MONTHS[m1 - 1]}${y1 === y2 ? '' : ` ${y1}`} – ${d2} ${SHORT_MONTHS[m2 - 1]} ${y2}`
}

/** The period button: 'This year · 1 Jan – 13 Oct 2026 · W1–42'. */
export function periodLabel(start: number, end: number, preset = ''): string {
  const w1 = isoWeek(start), w2 = isoWeek(end - 1)
  let weeks: string
  if (w1.year === w2.year && w1.week === w2.week) weeks = `W${w1.week}`
  else if (w1.year === w2.year) weeks = `W${w1.week}–${w2.week}`
  else weeks = end - start <= 92 ? `W${w1.week}–W${w2.week} ${w2.year}` : '' // across a new year: short periods only
  return [preset, datesText(start, end), weeks].filter(Boolean).join(' · ')
}

/** 'W41 · 5 Oct – 11 Oct' */
export function weekLabel(year: number, week: number): string {
  const start = weekMonday(year, week)
  const [, m1, d1] = ymd(start), [, m2, d2] = ymd(start + 6)
  return `W${week} · ${d1} ${SHORT_MONTHS[m1 - 1]} – ${d2} ${SHORT_MONTHS[m2 - 1]}`
}

// ---------------------------------------------------------------- quick choices --

/** [start, end) of a quick choice as of `today` (day number). Unknown names mean "This year". */
export function presetRange(name: string, today: number): [number, number] {
  const [y, m] = ymd(today)
  const tomorrow = today + 1
  const first = fromYmd(y, m, 1)
  const monday = today - weekday(today)
  const quarter = fromYmd(y, Math.floor((m - 1) / 3) * 3 + 1, 1)
  switch (name) {
    case 'Today': return [today, tomorrow]
    case 'Yesterday': return [today - 1, today]
    case 'Last 7 days': return [today - 6, tomorrow]
    case 'Last 30 days': return [today - 29, tomorrow]
    case 'This quarter': return [quarter, tomorrow]
    case 'Last quarter': return [fromYmd(y, Math.floor((m - 1) / 3) * 3 - 2, 1), quarter]
    case 'Last year': return [fromYmd(y - 1, 1, 1), fromYmd(y, 1, 1)]
    case 'This week': return [monday, tomorrow]
    case 'Last week': return [monday - 7, monday]
    case 'This month': return [first, tomorrow]
    case 'Last month': return [fromYmd(y, m - 1, 1), first]
    case 'Last 12 months': return [fromYmd(y, m - 11, 1), tomorrow]
    default: return [fromYmd(y, 1, 1), tomorrow] // This year
  }
}

// ---------------------------------------------------------------- comparisons --

export const wholeWeeks = (start: number, end: number): boolean => weekday(start) === 0 && (end - start) % 7 === 0

/** Compare with the same weeks last year: whole weeks picked on the calendar, or this / last week. */
export const isWeekly = (start: number, end: number, preset = ''): boolean =>
  preset === 'This week' || preset === 'Last week' || (!preset && wholeWeeks(start, end))

/** The same day some months later (negative: earlier); the month's last day if it is shorter. */
export function shiftMonths(day: number, months: number): number {
  const [y, m, d] = ymd(day)
  const [fy, fm] = ymd(fromYmd(y, m + months, 1))
  return fromYmd(fy, fm, Math.min(d, daysInMonth(fy, fm)))
}

/** The period a year earlier: weekly periods move back 52 weeks (Monday stays Monday), others keep
 * their dates (29 Feb becomes 28 Feb). */
export function sameLastYear(start: number, end: number, weekly = false): [number, number] {
  if (weekly) return [start - 364, end - 364]
  const shift = (day: number) => {
    const [y, m, d] = ymd(day)
    return fromYmd(y - 1, m, m === 2 && d === 29 ? 28 : d)
  }
  return [shift(start), shift(end)]
}

// How far back "previous period" goes for each quick choice: the same days of the previous week,
// month, quarter or year ("This month" 1-15 Oct is compared with 1-15 Sep), or the days just before.
const PREVIOUS: Record<string, ['days' | 'months', number, string]> = {
  Today: ['days', 1, 'yesterday'], Yesterday: ['days', 1, 'the day before'],
  'This week': ['days', 7, 'last week'], 'Last week': ['days', 7, 'the week before'],
  'Last 7 days': ['days', 7, 'the 7 days before'], 'Last 30 days': ['days', 30, 'the 30 days before'],
  'This month': ['months', 1, 'last month'], 'Last month': ['months', 1, 'the month before'],
  'This quarter': ['months', 3, 'last quarter'], 'Last quarter': ['months', 3, 'the quarter before'],
  'This year': ['months', 12, 'last year'], 'Last year': ['months', 12, 'the year before'],
  'Last 12 months': ['months', 12, 'the 12 months before'],
}

function previousShift(start: number, end: number, preset = ''): ['days' | 'months', number, string] {
  if (preset in PREVIOUS) return PREVIOUS[preset]
  const [sy, sm, sd] = ymd(start), [ey, em, ed] = ymd(end)
  if (sd === 1 && ed === 1) { // whole months picked on the calendar
    const months = (ey - sy) * 12 + em - sm
    return ['months', months, months === 1 ? 'the month before' : `the ${months} months before`]
  }
  const days = end - start
  if (days === 1) return ['days', 1, 'the day before']
  if (wholeWeeks(start, end)) {
    const weeks = days / 7
    return ['days', days, weeks === 1 ? 'the week before' : `the ${weeks} weeks before`]
  }
  return ['days', days, `the ${days} days before`]
}

/** The period just before this one, of the same kind; end exclusive. */
export function previousPeriod(start: number, end: number, preset = ''): [number, number] {
  const [unit, n] = previousShift(start, end, preset)
  if (unit === 'months') { // a period to the end of a month compares with whole months (all of August)
    const last = ymd(end)[2] === 1 ? shiftMonths(end, -n) : shiftMonths(end - 1, -n) + 1
    return [shiftMonths(start, -n), last]
  }
  return [start - n, end - n]
}

/** The dates a period is compared with, or null for no comparison. */
export function compareRange(mode: string, start: number, end: number, preset = '',
                             custom: [number, number] | null = null): [number, number] | null {
  if (mode === 'previous') return previousPeriod(start, end, preset)
  if (mode === 'last_year') return sameLastYear(start, end, isWeekly(start, end, preset))
  if (mode === 'custom' && custom) return custom
  return null
}

/** The comparison in a few words, for "+12% vs ...": 'last year', 'same weeks last year',
 * 'yesterday', 'last month', or the dates. */
export function compareName(mode: string, start: number, end: number, preset = '',
                            custom: [number, number] | null = null): string {
  if (mode === 'last_year') return isWeekly(start, end, preset) ? 'same weeks last year' : 'last year'
  if (mode === 'previous') return previousShift(start, end, preset)[2]
  if (mode === 'custom' && custom) return datesText(...custom)
  return ''
}
