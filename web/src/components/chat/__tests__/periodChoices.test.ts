// The "Dates" choice of "Add to dashboard" (dashboards.period_choices): its labels and the default.
import { describe, expect, it } from 'vitest'
import type { Table, Turn } from '../../../api/types'
import {
  ALL_DATES_LABEL, FOLLOW_LABEL, datesText, defaultBoardName, defaultPeriodMode, defaultTitle, defaultWidth,
  namedAfterDates, periodChoices, shortDates, titleWithoutPeriods,
} from '../periodChoices'

const today = new Date(2026, 9, 16) // 16 Oct 2026
const table = (...names: string[]): Table => ({
  columns: names.map(name => ({ name, type: 'text' as const })), rows: [], row_count: 0, truncated: false,
})
const answer = (periods: Turn['periods'], columns: string[] = ['Customer', 'Bookings'], kind = 'bar'): Pick<Turn, 'periods' | 'table' | 'chart' | 'question'> => ({
  question: 'Top 10 customers by bookings yesterday vs the day before',
  periods, table: table(...columns),
  chart: { kind, option: {}, title: 'Top 10 customers by bookings yesterday vs the day before', summary: '', note: '' },
})
const yesterdayVsDayBefore: Turn['periods'] = [
  { phrase: 'yesterday', start: '2026-10-15', end: '2026-10-16' },
  { phrase: 'the day before', start: '2026-10-14', end: '2026-10-15' },
]

describe('shortDates / datesText', () => {
  it('writes dates the way the dashboards do', () => {
    expect(shortDates('2026-10-15', '2026-10-16')).toBe('15 Oct 2026')
    expect(shortDates('2026-10-14', '2026-10-16', false)).toBe('14–15 Oct')
    expect(shortDates('2026-09-28', '2026-10-04', false)).toBe('28 Sep – 3 Oct')
    expect(shortDates('2025-12-28', '2026-01-04')).toBe('28 Dec 2025 – 3 Jan 2026')
  })

  it('joins periods that follow each other, else lists them', () => {
    const d = (s: string) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10))
    expect(datesText([[d('2026-10-15'), d('2026-10-16')], [d('2026-10-14'), d('2026-10-15')]], false)).toBe('14–15 Oct')
    expect(datesText([[d('2026-10-15'), d('2026-10-16')], [d('2026-09-15'), d('2026-09-16')]], false)).toBe('15 Oct vs 15 Sep')
  })
})

describe('periodChoices', () => {
  it('a question with its own periods keeps them by default', () => {
    const choices = periodChoices(answer(yesterdayVsDayBefore), today)
    expect(choices.map(c => c.mode)).toEqual(['own', 'fixed', 'dashboard'])
    expect(choices[0].label).toBe('Own period: yesterday vs the day before (14–15 Oct)')
    expect(choices[1].label).toBe('Fixed dates: 14–15 Oct 2026')
    expect(choices[2]).toEqual({ mode: 'dashboard', label: FOLLOW_LABEL, instant: false }) // two periods can't follow one
    expect(choices[0].instant && choices[1].instant).toBe(true)
    expect(defaultPeriodMode(answer(yesterdayVsDayBefore), today)).toBe('own')
  })

  it('one period of its own can also follow the dashboard at once', () => {
    const lastMonth = [{ phrase: 'last month', start: '2026-09-01', end: '2026-10-01' }]
    const choices = periodChoices(answer(lastMonth), today)
    expect(choices[0].label).toBe('Own period: last month (1–30 Sep)')
    expect(choices.find(c => c.mode === 'dashboard')?.instant).toBe(true)
  })

  it('shows the year when the period is not in this year', () => {
    const lastYear = [{ phrase: 'last December', start: '2025-12-01', end: '2026-01-01' }]
    expect(periodChoices(answer(lastYear), today)[0].label).toBe('Own period: last December (1–31 Dec 2025)')
  })

  it('a question without dates follows the dashboard by default', () => {
    const choices = periodChoices(answer([]), today)
    expect(choices).toEqual([
      { mode: 'dashboard', label: FOLLOW_LABEL, instant: false },
      { mode: 'fixed', label: ALL_DATES_LABEL, instant: true },
    ])
    expect(defaultPeriodMode(answer([]), today)).toBe('dashboard')
  })

  it('"own" is not offered when the columns are named after the dates', () => {
    const named = answer(yesterdayVsDayBefore, ['Customer', 'Bookings 15 Oct', 'Bookings 14 Oct'])
    expect(namedAfterDates(['Customer', 'Bookings 15 Oct'], yesterdayVsDayBefore)).toBe(true)
    expect(namedAfterDates(['Customer', 'Bookings'], yesterdayVsDayBefore)).toBe(false)
    expect(namedAfterDates(['Sales 2026-10-14'], yesterdayVsDayBefore)).toBe(true)
    const choices = periodChoices(named, today)
    expect(choices.map(c => c.mode)).toEqual(['dashboard', 'fixed'])
    expect(defaultPeriodMode(named, today)).toBe('dashboard')
  })
})

describe('defaults of the add form', () => {
  it('takes the periods out of the title', () => {
    expect(titleWithoutPeriods('Bookings yesterday vs the day before by customer', yesterdayVsDayBefore))
      .toBe('Bookings by customer')
    expect(defaultTitle(answer(yesterdayVsDayBefore))).toBe('Top 10 customers by bookings')
    expect(titleWithoutPeriods('Sales by month', [])).toBe('Sales by month')
  })

  it('maps and described charts take the full width', () => {
    expect(defaultWidth(answer([], ['Country', 'Bookings'], 'map'))).toBe('full')
    expect(defaultWidth(answer([], ['Country', 'Bookings'], 'custom'))).toBe('full')
    expect(defaultWidth(answer([]))).toBe('half')
  })

  it('names a dashboard made from a conversation after the day', () => {
    expect(defaultBoardName(today)).toBe('From chat · 16 Oct')
  })
})
