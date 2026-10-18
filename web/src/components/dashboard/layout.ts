// Where the chart cards go, as the old app placed them: half-width charts in pairs, a full-width chart
// on its own line (a half chart waiting for a partner before it is drawn alone, across the line), and
// the "Add chart" tile beside the last half chart or on its own line.
import type { ChartMeta } from '../../api/types'

export type Placed = { chart: ChartMeta; span: 1 | 2 }

export function placeCharts(charts: ChartMeta[]): { cards: Placed[]; tileSpan: 1 | 2 } {
  const cards: Placed[] = []
  let pending: ChartMeta | null = null
  for (const chart of charts) {
    if (chart.width === 'full') {
      if (pending) cards.push({ chart: pending, span: 2 })
      pending = null
      cards.push({ chart, span: 2 })
    } else if (pending) {
      cards.push({ chart: pending, span: 1 }, { chart, span: 1 })
      pending = null
    } else {
      pending = chart
    }
  }
  if (pending) {
    cards.push({ chart: pending, span: 1 })
    return { cards, tileSpan: 1 }
  }
  return { cards, tileSpan: 2 }
}
