// How a chat answer can go on a dashboard (the "Dates" choice of "Add to dashboard"), worked out in the
// browser the way dashboards.period_choices does on the server:
//   - the question names its own dates  → "Own period: yesterday vs the day before (14–15 Oct)" (suggested),
//                                          "Fixed dates: 14–15 Oct 2026", "Follow the dashboard's period"
//   - it names none                     → "Follow the dashboard's period" (suggested), "All dates, as in Chat"
//   - "own" is not possible (its columns are named after the dates, e.g. "Bookings 15 Oct": they would no
//     longer match once the dates move) → "Follow the dashboard's period" (suggested), "Fixed dates: …"
// instant = added in code at once (POST …/charts/from-answer); otherwise Claude rewrites the query (slow).
import type { PeriodMode, Turn } from '../../api/types'

export type PeriodChoice = { mode: PeriodMode; label: string; instant: boolean }
type Span = [number, number] // [start, end exclusive] as UTC milliseconds
type AnswerLike = Pick<Turn, 'periods' | 'table' | 'chart' | 'question'>

const DAY = 86_400_000
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
  'October', 'November', 'December']

function parse(iso: string): number {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return Date.UTC(y, m - 1, d)
}

const day = (t: number) => new Date(t).getUTCDate()
const month = (t: number) => MONTHS[new Date(t).getUTCMonth()]
const year = (t: number) => new Date(t).getUTCFullYear()

/** '15 Oct', '14–15 Oct', '28 Sep – 3 Oct', '28 Dec 2025 – 3 Jan 2026' (with the year if asked). */
export function shortDates(start: string | number, end: string | number, withYear = true): string {
  const s = typeof start === 'number' ? start : parse(start)
  const last = (typeof end === 'number' ? end : parse(end)) - DAY
  const tail = withYear ? ` ${year(last)}` : ''
  if (s >= last) return `${day(s)} ${month(s)}${tail}`
  if (year(s) === year(last) && month(s) === month(last)) return `${day(s)}–${day(last)} ${month(last)}${tail}`
  if (year(s) === year(last)) return `${day(s)} ${month(s)} – ${day(last)} ${month(last)}${tail}`
  return `${day(s)} ${month(s)} ${year(s)} – ${day(last)} ${month(last)} ${year(last)}`
}

/** One span when the periods follow each other ('14–15 Oct'), else each ('15 Oct vs 15 Sep'). */
export function datesText(spans: Span[], withYear: boolean): string {
  if (!spans.length) return ''
  const ordered = [...spans].sort((a, b) => a[0] - b[0] || a[1] - b[1])
  const joined = ordered.every((a, i) => i === 0 || ordered[i - 1][1] === a[0])
  if (joined) return shortDates(ordered[0][0], ordered[ordered.length - 1][1], withYear)
  return spans.map(([s, e]) => shortDates(s, e, withYear)).join(' vs ')
}

function spansOf(periods: Turn['periods']): Span[] {
  return (periods ?? []).map(p => [parse(p.start), parse(p.end)])
}

const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Whether the result's columns are named after the periods' days ("Bookings 15 Oct"). */
export function namedAfterDates(names: string[], periods: Turn['periods']): boolean {
  const text = names.join(' | ').toLowerCase()
  const spans = spansOf(periods)
  if (!text || !spans.length) return false
  for (const [s, e] of spans) {
    for (let i = 0; i < Math.min(Math.round((e - s) / DAY), 400); i++) {
      const t = s + i * DAY
      const d = new Date(t)
      const dd = d.getUTCDate(), mm = d.getUTCMonth(), yy = d.getUTCFullYear()
      const pad = (n: number) => String(n).padStart(2, '0')
      const forms = [
        `${yy}-${pad(mm + 1)}-${pad(dd)}`, `${dd} ${MONTHS[mm]}`, `${MONTHS[mm]} ${dd}`, `${dd} ${MONTHS_LONG[mm]}`,
        `${MONTHS_LONG[mm]} ${dd}`, `${dd}/${mm + 1}`, `${pad(dd)}/${pad(mm + 1)}`, `${MONTHS[mm]} ${yy}`,
        `${MONTHS_LONG[mm]} ${yy}`,
      ]
      for (const form of forms) {
        if (new RegExp(`(?<![\\w])${escape(form.toLowerCase())}(?![\\w])`).test(text)) return true
      }
    }
  }
  return false
}

/** "Own period: yesterday vs the day before (14–15 Oct)": the year only when it isn't this year. */
export function ownLabel(periods: Turn['periods'], today: Date = new Date()): string {
  const spans = spansOf(periods)
  const thisYear = today.getFullYear()
  const sameYear = spans.every(([s, e]) => year(s) === thisYear && year(e - DAY) === thisYear)
  return `Own period: ${periods.map(p => p.phrase).join(' vs ')} (${datesText(spans, !sameYear)})`
}

export function fixedLabel(periods: Turn['periods']): string {
  return `Fixed dates: ${datesText(spansOf(periods), true)}`
}

export const FOLLOW_LABEL = "Follow the dashboard's period"
export const ALL_DATES_LABEL = 'All dates, as in Chat'

/** The ways this answer can go on a dashboard, the suggested one first. */
export function periodChoices(turn: AnswerLike, today: Date = new Date()): PeriodChoice[] {
  const periods = turn.periods ?? []
  const names = (turn.table?.columns ?? []).map(c => c.name)
  const named = namedAfterDates(names, periods)
  // in code only for one period of its own (the server also checks that it filters a range of days)
  const follow: PeriodChoice = { mode: 'dashboard', label: FOLLOW_LABEL, instant: periods.length === 1 && !named }
  if (!periods.length) return [follow, { mode: 'fixed', label: ALL_DATES_LABEL, instant: true }]
  const fixed: PeriodChoice = { mode: 'fixed', label: fixedLabel(periods), instant: true }
  if (named) return [follow, fixed]
  return [{ mode: 'own', label: ownLabel(periods, today), instant: true }, fixed, follow]
}

/** The suggested choice: its own period when the question names one, else the dashboard's. */
export function defaultPeriodMode(turn: AnswerLike, today: Date = new Date()): PeriodMode {
  return periodChoices(turn, today)[0].mode
}

/** A chart title without the question's periods ("Bookings yesterday vs the day before by customer" →
 * "Bookings by customer"): the card on the dashboard says which dates it shows. The server cleans it
 * again (dashboards._title_without_periods); this is what the title box starts with. */
export function titleWithoutPeriods(title: string, periods: Turn['periods']): string {
  let text = title
  const phrases = (periods ?? []).map(p => (p.phrase || '').trim()).filter(Boolean).sort((a, b) => b.length - a.length)
  for (const phrase of phrases) text = text.replace(new RegExp(`(?<!\\w)${escape(phrase)}(?!\\w)`, 'gi'), '\u0000')
  const joiner = '\\s*(?:,|vs\\.?|versus|and|compared (?:with|to)|to)\\s*'
  text = text.replace(new RegExp(`(?:\\b(?:over|for|on|in|between|from|during)\\s+)?\u0000(?:${joiner}\u0000)*`, 'gi'), ' ')
  text = text.replace(/\s{2,}/g, ' ').trim()
  text = text.replace(/(?:^|(?<=[\s,;:(]))(?:vs\.?|versus)\s*(?=$|[,;:)]|by\b|per\b)/gi, '')
  text = text.replace(/\s{2,}/g, ' ').replace(/\s+([,;:)])/g, '$1')
  text = text.replace(/[\s,;:\-–—·|]+$/, '').trim()
  return text || title
}

export function defaultTitle(turn: AnswerLike): string {
  return titleWithoutPeriods(turn.chart?.title || turn.question, turn.periods ?? [])
}

/** Maps and charts described in words take the full width, the rest half (views/chat.py). */
export function defaultWidth(turn: AnswerLike): 'half' | 'full' {
  return ['map', 'custom'].includes(turn.chart?.kind ?? '') ? 'full' : 'half'
}

/** The name a dashboard made from a conversation starts with: "From chat · 16 Oct". */
export function defaultBoardName(today: Date = new Date()): string {
  return `From chat · ${today.getDate()} ${MONTHS[today.getMonth()]}`
}
