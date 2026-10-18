// The dashboard's filters in the address (?f_client=…) and in the results query.
import { describe, expect, it } from 'vitest'
import { readFilters, resultsParams, resultsQuery, writeFilter, writeSearch } from './periodState'

const period = { preset: 'Last 7 days', start: '2026-10-11', end: '2026-10-18' }
const compare = { mode: 'previous' as const, start: '', end: '' }

describe('dashboard filters', () => {
  it('reads only the filters the dashboard has', () => {
    const search = new URLSearchParams('preset=Last+7+days&f_client=1042&f_market=SAUDI+ARABIA&f_other=x')
    expect(readFilters(search, ['client', 'market'])).toEqual({ client: '1042', market: 'SAUDI ARABIA' })
    expect(readFilters(search, [])).toEqual({})
  })

  it('a filter picked stays when the period changes, and goes when cleared', () => {
    let search = writeFilter(new URLSearchParams('preset=Last+7+days'), 'client', 'O\'Hara & Sons')
    search = writeSearch({ preset: 'This month', start: '2026-10-01', end: '2026-10-18' }, compare, search)
    expect(readFilters(search, ['client'])).toEqual({ client: 'O\'Hara & Sons' })
    expect(readFilters(writeFilter(search, 'client', ''), ['client'])).toEqual({})
  })

  it('travel to the server as f_<key>, and only when there are some (same cache key as before otherwise)', () => {
    expect(resultsParams(period, compare)).not.toHaveProperty('filters')
    const params = resultsParams(period, compare, { market: 'SAUDI ARABIA' })
    expect(new URLSearchParams(resultsQuery(params)).get('f_market')).toBe('SAUDI ARABIA')
    expect(resultsQuery(resultsParams(period, compare))).toBe('start=2026-10-11&end=2026-10-18&preset=Last+7+days&compare=previous')
  })
})
