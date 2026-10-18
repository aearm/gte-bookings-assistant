import { describe, expect, it } from 'vitest'
import {
  compareName, compareRange, datesText, isoWeek, periodLabel, presetRange, previousPeriod, sameLastYear, toDay, toIso,
  weekLabel, weekMonday, weekRange, weeksInYear, weeksOf,
} from './periods'
import { compareButtonLabel, readCompare, readPeriod, resultsParams, resultsQuery, writeSearch } from './periodState'

const d = toDay
const iso = ([a, b]: [number, number]) => [toIso(a), toIso(b)]
const TODAY = d('2026-10-16') // a Friday

describe('ISO weeks', () => {
  it('start on Monday; week 1 holds the first Thursday', () => {
    expect(isoWeek(d('2025-12-29'))).toEqual({ year: 2026, week: 1 })
    expect(isoWeek(d('2026-01-01'))).toEqual({ year: 2026, week: 1 })
    expect(isoWeek(d('2026-10-16'))).toEqual({ year: 2026, week: 42 })
    expect(isoWeek(d('2027-01-01'))).toEqual({ year: 2026, week: 53 })
    expect(isoWeek(d('2021-01-03'))).toEqual({ year: 2020, week: 53 })
    expect(weeksInYear(2026)).toBe(53)
    expect(weeksInYear(2025)).toBe(52)
    expect(toIso(weekMonday(2026, 1))).toBe('2025-12-29')
    expect(toIso(weekMonday(2026, 42))).toBe('2026-10-12')
  })

  it('ranges of weeks, clamped to the year', () => {
    expect(iso(weekRange(2026, 40, 41))).toEqual(['2026-09-28', '2026-10-12'])
    expect(iso(weekRange(2026, 41, 40))).toEqual(['2026-09-28', '2026-10-12'])
    expect(iso(weekRange(2025, 53))).toEqual(['2025-12-22', '2025-12-29'])
    expect(weekLabel(2026, 41)).toBe('W41 · 5 Oct – 11 Oct')
    expect(weeksOf(d('2026-10-05'), d('2026-10-12'))).toBe('week 41')
    expect(weeksOf(d('2026-01-01'), d('2026-10-17'))).toBe('weeks 1–42')
    expect(weeksOf(d('2025-12-22'), d('2026-01-19'))).toBe('weeks 52 (2025) – 3 (2026)')
  })
})

describe('labels', () => {
  it('write the dates and weeks of a period', () => {
    expect(datesText(d('2026-01-01'), d('2026-10-17'))).toBe('1 Jan – 16 Oct 2026')
    expect(datesText(d('2026-10-05'), d('2026-10-06'))).toBe('5 Oct 2026')
    expect(datesText(d('2025-12-29'), d('2026-01-05'))).toBe('29 Dec 2025 – 4 Jan 2026')
    expect(periodLabel(d('2026-01-01'), d('2026-10-17'), 'This year')).toBe('This year · 1 Jan – 16 Oct 2026 · W1–42')
    expect(periodLabel(d('2026-10-10'), d('2026-10-17'), 'Last 7 days')).toBe('Last 7 days · 10 Oct – 16 Oct 2026 · W41–42')
    expect(periodLabel(d('2026-10-12'), d('2026-10-13'))).toBe('12 Oct 2026 · W42')
    expect(periodLabel(d('2025-12-22'), d('2026-01-12'))).toBe('22 Dec 2025 – 11 Jan 2026 · W52–W2 2026')
    expect(periodLabel(d('2025-06-01'), d('2026-02-01'))).toBe('1 Jun 2025 – 31 Jan 2026') // long: no weeks
  })
})

describe('quick choices', () => {
  it.each([
    ['Today', '2026-10-16', '2026-10-17'], ['Yesterday', '2026-10-15', '2026-10-16'],
    ['This week', '2026-10-12', '2026-10-17'], ['Last week', '2026-10-05', '2026-10-12'],
    ['Last 7 days', '2026-10-10', '2026-10-17'], ['Last 30 days', '2026-09-17', '2026-10-17'],
    ['This month', '2026-10-01', '2026-10-17'], ['Last month', '2026-09-01', '2026-10-01'],
    ['This quarter', '2026-10-01', '2026-10-17'], ['Last quarter', '2026-07-01', '2026-10-01'],
    ['This year', '2026-01-01', '2026-10-17'], ['Last year', '2025-01-01', '2026-01-01'],
    ['Last 12 months', '2025-11-01', '2026-10-17'],
  ])('%s', (name, start, end) => {
    expect(iso(presetRange(name, TODAY))).toEqual([start, end])
  })

  it('last quarter at the start of a year', () => {
    expect(iso(presetRange('Last quarter', d('2026-02-10')))).toEqual(['2025-10-01', '2026-01-01'])
  })
})

describe('comparisons', () => {
  it('previous period of the same kind', () => {
    expect(iso(previousPeriod(d('2026-10-01'), d('2026-10-16'), 'This month'))).toEqual(['2026-09-01', '2026-09-16'])
    expect(iso(previousPeriod(d('2026-10-10'), d('2026-10-17'), 'Last 7 days'))).toEqual(['2026-10-03', '2026-10-10'])
    expect(iso(previousPeriod(d('2026-08-01'), d('2026-10-01')))).toEqual(['2026-06-01', '2026-08-01'])
    expect(iso(previousPeriod(d('2026-03-31'), d('2026-04-01'), 'This month'))).toEqual(['2026-02-28', '2026-03-01'])
    expect(iso(previousPeriod(d('2026-09-28'), d('2026-10-12')))).toEqual(['2026-09-14', '2026-09-28'])
    expect(compareName('previous', d('2026-09-28'), d('2026-10-12'))).toBe('the 2 weeks before')
    expect(compareName('previous', d('2026-10-03'), d('2026-10-06'))).toBe('the 3 days before')
    expect(compareName('previous', d('2026-08-01'), d('2026-10-01'))).toBe('the 2 months before')
    expect(compareName('previous', d('2026-10-15'), d('2026-10-16'), 'Yesterday')).toBe('the day before')
  })

  it('same period last year: weeks stay weeks, 29 Feb becomes 28 Feb', () => {
    expect(iso(sameLastYear(d('2026-10-05'), d('2026-10-12'), true))).toEqual(['2025-10-06', '2025-10-13'])
    expect(iso(sameLastYear(d('2024-02-29'), d('2024-03-01')))).toEqual(['2023-02-28', '2023-03-01'])
    expect(iso(compareRange('last_year', d('2026-01-01'), d('2026-10-17'), 'This year')!)).toEqual(['2025-01-01', '2025-10-17'])
    expect(compareName('last_year', d('2026-10-05'), d('2026-10-12'))).toBe('same weeks last year')
    expect(compareRange('none', d('2026-01-01'), d('2026-01-02'))).toBeNull()
    expect(compareName('custom', 0, 1, '', [d('2026-09-01'), d('2026-09-16')])).toBe('1 Sep – 15 Sep 2026')
  })
})

describe('the period in the address', () => {
  const defaults = { preset: 'Last 7 days', compare: 'previous' }

  it('reads a quick choice, picked dates or the defaults', () => {
    expect(readPeriod(new URLSearchParams(''), defaults, '2026-10-16'))
      .toEqual({ preset: 'Last 7 days', start: '2026-10-10', end: '2026-10-17' })
    expect(readPeriod(new URLSearchParams('preset=This+year'), defaults, '2026-10-16'))
      .toEqual({ preset: 'This year', start: '2026-01-01', end: '2026-10-17' })
    expect(readPeriod(new URLSearchParams('start=2026-09-28&end=2026-10-12'), defaults, '2026-10-16'))
      .toEqual({ preset: '', start: '2026-09-28', end: '2026-10-12' })
    expect(readPeriod(new URLSearchParams('start=2026-10-12&end=2026-10-01'), defaults, '2026-10-16').preset).toBe('Last 7 days')
    expect(readCompare(new URLSearchParams(''), defaults)).toEqual({ mode: 'previous', start: '', end: '' })
    expect(readCompare(new URLSearchParams('compare=custom'), defaults).mode).toBe('previous') // no dates
    expect(readCompare(new URLSearchParams('compare=custom&cstart=2026-09-01&cend=2026-09-08'), defaults))
      .toEqual({ mode: 'custom', start: '2026-09-01', end: '2026-09-08' })
  })

  it('writes it back and asks the server for it', () => {
    const period = { preset: '', start: '2026-09-28', end: '2026-10-12' }
    const compare = { mode: 'last_year' as const, start: '', end: '' }
    expect(writeSearch(period, compare).toString()).toBe('start=2026-09-28&end=2026-10-12&compare=last_year')
    expect(writeSearch({ ...period, preset: 'This year' }, compare).toString()).toBe('preset=This+year&compare=last_year')
    expect(resultsQuery(resultsParams(period, compare), true))
      .toBe('start=2026-09-28&end=2026-10-12&compare=last_year&force=true')
    expect(compareButtonLabel(period, compare)).toBe('vs 29 Sep – 12 Oct 2025')
    expect(compareButtonLabel(period, { mode: 'none', start: '', end: '' })).toBe('Compare')
  })
})
