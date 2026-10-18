import { describe, expect, it } from 'vitest'
import type { UsageEntry } from '../types'
import { cacheUse, costFromDaily, firstDay, inLastDays, kindLabel, median, newestFirst, RECENT_LIMIT, stageTimes, summarize, summaryWindows, windowLabel } from '../usageSummary'

const today = new Date(2026, 9, 16)   // 16 Oct 2026, local
const entry = (over: Partial<UsageEntry>): UsageEntry => ({
  time: '2026-10-16T10:00:00', kind: 'question', label: 'q', seconds: 10, cost: 0.02, claude_calls: 2, ...over,
})
const entries: UsageEntry[] = [
  entry({ time: '2026-10-16T09:00:00', seconds: 8, cost: 0.02, stages: { plan: 4, query: 3 }, cache_hit: 0.5,
          input_tokens: 100, cache_read_tokens: 300, cache_write_tokens: 0 }),
  entry({ time: '2026-10-16T11:30:00', seconds: 12, cost: 0, claude_calls: 0, memory: true, stages: { query: 2 } }),
  entry({ time: '2026-10-12T15:00:00', seconds: 20, cost: 0.04, stages: { plan: 8, query: 10 }, cache_hit: 0.25,
          input_tokens: 300, cache_read_tokens: 100, cache_write_tokens: 0 }),
  entry({ time: '2026-10-12T15:05:00', kind: 'dashboard_chart', label: 'chart', seconds: 30, cost: 0.1, cache_hit: 0,
          input_tokens: 400, cache_read_tokens: 0, cache_write_tokens: 0 }),
  entry({ time: '2026-09-20T08:00:00', seconds: 6, cost: 0.01, cache_hit: 1, input_tokens: 0, cache_read_tokens: 50, cache_write_tokens: 0 }),
]

describe('periods', () => {
  it('counts the last N days including today, as cost_report does', () => {
    expect(firstDay(today, 1)).toBe('2026-10-16')
    expect(firstDay(today, 7)).toBe('2026-10-10')
    expect(firstDay(today, 30)).toBe('2026-09-17')
    expect(inLastDays(entries, 1, today)).toHaveLength(2)
    expect(inLastDays(entries, 7, today)).toHaveLength(4)
    expect(inLastDays(entries, 30, today)).toHaveLength(5)
  })

  it('shows today, 7 days and the period picked', () => {
    expect(summaryWindows(30)).toEqual([1, 7, 30])
    expect(summaryWindows(7)).toEqual([1, 7])
    expect(summaryWindows(90)).toEqual([1, 7, 90])
    expect(windowLabel(1)).toBe('Today')
    expect(windowLabel(30)).toBe('Last 30 days')
  })
})

describe('summarize', () => {
  it('counts questions, all of Claude cost, and the average per question', () => {
    const week = summarize(entries, 7, today)
    expect(week.questions).toBe(3)
    expect(week.cost).toBeCloseTo(0.16)
    expect(week.averageCost).toBeCloseTo(0.02)        // (0.02 + 0 + 0.04) / 3
    expect(week.fromMemory).toBe(1)
    expect(week.medianSeconds).toBe(12)
  })

  it("takes the cost of every activity from the server's daily report when it covers the period", () => {
    const daily = Array.from({ length: 7 }, (_, i) => ({ Day: `2026-10-${String(10 + i).padStart(2, '0')}`, 'Cost ($)': 1 }))
    expect(costFromDaily(daily, '2026-10-14')).toBe(3)
    expect(costFromDaily(daily, '2026-10-01')).toBeNull()       // the report starts later
    expect(summarize(entries, 7, today, daily).cost).toBe(7)
    expect(summarize(entries, 1, today, daily).cost).toBe(1)
    expect(summarize(entries, 30, today, daily).cost).toBeCloseTo(0.17)   // falls back to the entries
  })

  it('says when the latest questions do not reach back to the start of the period', () => {
    const many = Array.from({ length: RECENT_LIMIT }, () => entry({ time: '2026-10-15T10:00:00' }))
    expect(summarize(many, 1, today).partial).toBe(false)
    expect(summarize(many, 7, today).partial).toBe(true)
    expect(summarize(entries, 30, today).partial).toBe(false)
  })

  it('has no average and no cache use when there is nothing', () => {
    const empty = summarize([], 7, today)
    expect(empty).toMatchObject({ questions: 0, cost: 0, averageCost: null, cacheUse: null, medianSeconds: null })
  })

  it('weighs cache use by tokens when the entries carry them', () => {
    // today: only the first entry made Claude calls: 300 read of 400
    expect(summarize(entries, 1, today).cacheUse).toBeCloseTo(0.75)
    // 7 days: 400 read of 1200
    expect(cacheUse(inLastDays(entries, 7, today))).toBeCloseTo(400 / 1200)
  })

  it('falls back to the average cache_hit without token counts', () => {
    const rows = [entry({ cache_hit: 0.2 }), entry({ cache_hit: 0.6 }), entry({ claude_calls: 0, cache_hit: 0 })]
    expect(cacheUse(rows)).toBeCloseTo(0.4)
  })
})

describe('stageTimes', () => {
  it('averages each stage over the questions that went through it, slowest first', () => {
    const stages = stageTimes(inLastDays(entries, 7, today))
    expect(stages.map((s) => s.stage)).toEqual(['plan', 'query'])
    expect(stages[0]).toMatchObject({ stage: 'plan', questions: 2, average: 6, longest: 8 })
    expect(stages[1]).toMatchObject({ stage: 'query', questions: 3, average: 5, longest: 10 })
    expect(stages[0].share).toBeCloseTo(12 / 28)      // 12 s of plan in 28 s of those questions
  })

  it('leaves out other kinds of entries', () => {
    expect(stageTimes([entry({ kind: 'dashboard_chart', stages: { plan: 5 } })])).toEqual([])
  })
})

describe('helpers', () => {
  it('median', () => {
    expect(median([3, 1, 2])).toBe(2)
    expect(median([4, 1, 2, 3])).toBe(2.5)
    expect(median([])).toBeNull()
  })

  it('newest first, limited', () => {
    expect(newestFirst(entries, 2).map((e) => e.time)).toEqual(['2026-10-16T11:30:00', '2026-10-16T09:00:00'])
  })

  it('names the kinds as the cost report does', () => {
    expect(kindLabel('question')).toBe('Questions in Chat')
    expect(kindLabel('layer_build')).toBe('Data layer builds')
    expect(kindLabel('something_new')).toBe('something_new')
  })
})
