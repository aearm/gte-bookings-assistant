import { describe, expect, it } from 'vitest'
import type { ChartMeta } from '../../api/types'
import { placeCharts } from './layout'

const chart = (id: string, width: 'half' | 'full'): ChartMeta => ({
  id, title: id, question: '', chart_type: 'bar', width, cubes: [], date_column: '',
  period: { mode: 'dashboard', label: '' }, compares: true,
})

const spans = (charts: ChartMeta[]) => {
  const { cards, tileSpan } = placeCharts(charts)
  return [cards.map((c) => `${c.chart.id}:${c.span}`).join(' '), tileSpan]
}

describe('placeCharts', () => {
  it('pairs half charts and gives full charts a line', () => {
    expect(spans([chart('a', 'half'), chart('b', 'half'), chart('c', 'full')])).toEqual(['a:1 b:1 c:2', 2])
  })
  it('a half chart before a full one takes the whole line', () => {
    expect(spans([chart('a', 'half'), chart('b', 'full'), chart('c', 'half')])).toEqual(['a:2 b:2 c:1', 1])
  })
  it('the add tile sits beside a last half chart', () => {
    expect(spans([chart('a', 'half')])).toEqual(['a:1', 1])
    expect(spans([])).toEqual(['', 2])
  })
})
