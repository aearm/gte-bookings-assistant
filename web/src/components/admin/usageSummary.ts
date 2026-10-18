// Figures of the Usage page, worked out from the usage entries the server sends (data/usage.jsonl lines:
// the latest questions) and its cost report (every Claude activity, per day).
// Entry times are the server's local time written without a zone ("2026-10-16T14:05:09"), so periods
// are compared on the date text, which keeps them right whatever the browser's time zone.
import type { CostReport, UsageEntry } from './types'

/** The server sends at most this many recent questions. */
export const RECENT_LIMIT = 300

export const ACTIVITIES: Record<string, string> = {
  question: 'Questions in Chat', dashboard_chart: 'Dashboard charts', chart_restyle: 'Chart redraws',
  layer_build: 'Data layer builds', cube_setup: 'Cube setup', claude_call: 'Other',
}
export const kindLabel = (kind: string) => ACTIVITIES[kind] ?? kind

/** YYYY-MM-DD of a local date */
export function dayKey(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/** The first day of "the last `days` days" ending today (1 = today only), as usage.cost_report counts. */
export function firstDay(today: Date, days: number): string {
  const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - Math.max(days, 1) + 1)
  return dayKey(d)
}

export function inLastDays(entries: UsageEntry[], days: number, today: Date): UsageEntry[] {
  const from = firstDay(today, days)
  return entries.filter((e) => (e.time ?? '').slice(0, 10) >= from)
}

export type WindowSummary = {
  days: number
  questions: number          // questions asked in Chat
  cost: number               // what Claude cost: everything (from the daily report), else the entries'
  partial: boolean           // the entries don't reach back to the start of the period (the latest 300 only)
  averageCost: number | null // per question
  cacheUse: number | null    // share of prompt tokens read from Claude's cache (0-1)
  fromMemory: number         // questions answered from memory (no Claude call for the plan)
  medianSeconds: number | null
}

export function median(values: number[]): number | null {
  if (!values.length) return null
  const s = [...values].sort((a, b) => a - b)
  const mid = Math.floor(s.length / 2)
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2
}

/** Cache use weighted by tokens when the entries carry them, else the average of their cache_hit. */
export function cacheUse(entries: UsageEntry[]): number | null {
  const withCalls = entries.filter((e) => (e.claude_calls ?? 0) > 0)
  if (!withCalls.length) return null
  const tokens = withCalls.filter((e) => e.cache_read_tokens != null && e.input_tokens != null)
  if (tokens.length === withCalls.length) {
    const read = tokens.reduce((s, e) => s + (e.cache_read_tokens ?? 0), 0)
    const all = tokens.reduce((s, e) => s + (e.cache_read_tokens ?? 0) + (e.input_tokens ?? 0) + (e.cache_write_tokens ?? 0), 0)
    if (all > 0) return read / all
  }
  return withCalls.reduce((s, e) => s + (e.cache_hit ?? 0), 0) / withCalls.length
}

/** The cost of the period from the daily report, if the report reaches back to its first day. */
export function costFromDaily(daily: CostReport['daily'] | undefined, from: string): number | null {
  if (!daily?.length || daily[0].Day.slice(0, 10) > from) return null
  return daily.filter((d) => d.Day.slice(0, 10) >= from).reduce((s, d) => s + (d['Cost ($)'] ?? 0), 0)
}

export function summarize(entries: UsageEntry[], days: number, today: Date, daily?: CostReport['daily']): WindowSummary {
  const from = firstDay(today, days)
  const all = inLastDays(entries, days, today)
  const questions = all.filter((e) => e.kind === 'question')
  const cost = costFromDaily(daily, from) ?? all.reduce((s, e) => s + (e.cost ?? 0), 0)
  const questionCost = questions.reduce((s, e) => s + (e.cost ?? 0), 0)
  const oldest = entries.reduce((min, e) => ((e.time ?? '') < min ? e.time : min), '9999')
  return {
    days, questions: questions.length, cost,
    partial: entries.length >= RECENT_LIMIT && oldest.slice(0, 10) > from,
    averageCost: questions.length ? questionCost / questions.length : null,
    cacheUse: cacheUse(all),
    fromMemory: questions.filter((e) => e.memory).length,
    medianSeconds: median(questions.map((e) => e.seconds ?? 0)),
  }
}

/** The periods the summary shows: today, the last 7 days, and the period picked (when longer). */
export function summaryWindows(days: number): number[] {
  return [...new Set([1, 7, days])].sort((a, b) => a - b)
}

export const windowLabel = (days: number) => (days === 1 ? 'Today' : `Last ${days} days`)

export type StageTime = { stage: string; questions: number; average: number; longest: number; share: number }

/** How long each stage of answering takes (questions only), slowest first. `share` is the stage's part
 * of the time of the questions that went through it. */
export function stageTimes(entries: UsageEntry[]): StageTime[] {
  const by = new Map<string, { n: number; total: number; longest: number; questionSeconds: number }>()
  for (const e of entries) {
    if (e.kind !== 'question' || !e.stages) continue
    for (const [stage, secs] of Object.entries(e.stages)) {
      const s = by.get(stage) ?? { n: 0, total: 0, longest: 0, questionSeconds: 0 }
      s.n += 1
      s.total += secs
      s.longest = Math.max(s.longest, secs)
      s.questionSeconds += e.seconds ?? 0
      by.set(stage, s)
    }
  }
  return [...by.entries()]
    .map(([stage, s]) => ({ stage, questions: s.n, average: s.total / s.n, longest: s.longest,
                            share: s.questionSeconds > 0 ? Math.min(s.total / s.questionSeconds, 1) : 0 }))
    .sort((a, b) => b.average - a.average)
}

/** Newest first, at most `limit`. */
export function newestFirst(entries: UsageEntry[], limit = 300): UsageEntry[] {
  return [...entries].sort((a, b) => (b.time ?? '').localeCompare(a.time ?? '')).slice(0, limit)
}
