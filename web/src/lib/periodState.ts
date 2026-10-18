// The dashboard's period and comparison, kept in the page address (?preset=…&start=…&end=…&compare=…)
// so links and reloads show the same dates. A quick choice ("Last 7 days") is kept by name and means
// that period as of today; days picked on the calendar are kept as dates (end exclusive).
import {
  COMPARE_MODES, DEFAULT_COMPARE, DEFAULT_PRESET, compareName, compareRange, datesText, isCompareMode, isIsoDate,
  isPreset, periodLabel, presetRange, toDay, toIso, type CompareMode,
} from './periods'

export type PeriodChoice = { preset: string; start: string; end: string } // preset '' for picked dates
export type CompareChoice = { mode: CompareMode; start: string; end: string } // dates only for 'custom'
export type Defaults = { preset: string; compare: string }

/** The query of GET /dashboards/{id}/results (and the results' cache key). */
export type ResultsParams = {
  start: string; end: string; preset: string; compare: CompareMode; cstart: string; cend: string
  /** The dashboard's filters picked (?f_client=…), when it has any. */
  filters?: Record<string, string>
}

export function presetChoice(preset: string, today: string): PeriodChoice {
  const [start, end] = presetRange(preset, toDay(today))
  return { preset, start: toIso(start), end: toIso(end) }
}

/** The period in the address, else the default (from /api/info). */
export function readPeriod(search: URLSearchParams, defaults: Defaults | undefined, today: string): PeriodChoice {
  const preset = search.get('preset')
  if (isPreset(preset)) return presetChoice(preset!, today)
  const start = search.get('start'), end = search.get('end')
  if (isIsoDate(start) && isIsoDate(end) && toDay(end) > toDay(start)) return { preset: '', start, end }
  return presetChoice(isPreset(defaults?.preset) ? defaults!.preset : DEFAULT_PRESET, today)
}

/** The comparison in the address, else the default. Other dates without valid dates fall back too. */
export function readCompare(search: URLSearchParams, defaults: Defaults | undefined): CompareChoice {
  const mode = search.get('compare')
  const fallback: CompareMode = isCompareMode(defaults?.compare) && defaults!.compare !== 'custom'
    ? defaults!.compare as CompareMode : DEFAULT_COMPARE
  if (!isCompareMode(mode)) return { mode: fallback, start: '', end: '' }
  if (mode !== 'custom') return { mode, start: '', end: '' }
  const start = search.get('cstart'), end = search.get('cend')
  if (isIsoDate(start) && isIsoDate(end) && toDay(end) > toDay(start)) return { mode, start, end }
  return { mode: fallback, start: '', end: '' }
}

/** The address query for a period and comparison. */
export function writeSearch(period: PeriodChoice, compare: CompareChoice, keep?: URLSearchParams): URLSearchParams {
  const out = new URLSearchParams(keep)
  for (const key of ['preset', 'start', 'end', 'compare', 'cstart', 'cend']) out.delete(key)
  if (period.preset) out.set('preset', period.preset)
  else {
    out.set('start', period.start)
    out.set('end', period.end)
  }
  out.set('compare', compare.mode)
  if (compare.mode === 'custom') {
    out.set('cstart', compare.start)
    out.set('cend', compare.end)
  }
  return out
}

export function resultsParams(period: PeriodChoice, compare: CompareChoice,
                              filters: Record<string, string> = {}): ResultsParams {
  const custom = compare.mode === 'custom'
  return { start: period.start, end: period.end, preset: period.preset, compare: compare.mode,
           cstart: custom ? compare.start : '', cend: custom ? compare.end : '',
           ...(Object.keys(filters).length ? { filters } : {}) }
}

export function resultsQuery(params: ResultsParams, force = false): string {
  const q = new URLSearchParams()
  const { filters, ...rest } = params
  for (const [k, v] of Object.entries(rest)) if (v) q.set(k, v)
  for (const [k, v] of Object.entries(filters ?? {})) if (v) q.set(`f_${k}`, v)
  if (force) q.set('force', 'true')
  return q.toString()
}

// ---------------------------------------------------------------- the dashboard's filters --
// Kept in the address as f_<key>=<value> (?f_client=1042), so a link opens the same client or market.

/** The filters picked in the address, of those the dashboard has. */
export function readFilters(search: URLSearchParams, keys: string[]): Record<string, string> {
  const out: Record<string, string> = {}
  for (const key of keys) {
    const value = search.get(`f_${key}`)
    if (value) out[key] = value
  }
  return out
}

export function writeFilter(search: URLSearchParams, key: string, value: string): URLSearchParams {
  const out = new URLSearchParams(search)
  if (value) out.set(`f_${key}`, value)
  else out.delete(`f_${key}`)
  return out
}

// ---------------------------------------------------------------- words for the pickers --

export function choiceLabel(period: PeriodChoice): string {
  return periodLabel(toDay(period.start), toDay(period.end), period.preset)
}

export function customRange(compare: CompareChoice): [number, number] | null {
  return compare.mode === 'custom' && compare.start && compare.end ? [toDay(compare.start), toDay(compare.end)] : null
}

/** The dates a comparison mode gives for this period ([start, end) day numbers), or null. */
export function compareDates(mode: string, period: PeriodChoice, custom: [number, number] | null): [number, number] | null {
  return compareRange(mode, toDay(period.start), toDay(period.end), period.preset, custom)
}

/** The comparison button: 'vs 3 Oct – 9 Oct 2026', or 'Compare' when there is none. */
export function compareButtonLabel(period: PeriodChoice, compare: CompareChoice): string {
  const dates = compareDates(compare.mode, period, customRange(compare))
  return dates ? `vs ${datesText(...dates)}` : 'Compare'
}

/** 'the 7 days before', 'last year', … for "+12% vs …". */
export function compareWords(period: PeriodChoice, compare: CompareChoice): string {
  return compareName(compare.mode, toDay(period.start), toDay(period.end), period.preset, customRange(compare))
}

export const COMPARE_ORDER = Object.keys(COMPARE_MODES) as CompareMode[]
