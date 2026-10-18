// The words under a chart's title: which cubes, which date, and which period it shows.
import type { ChartMeta, ChartResult, Table } from '../../api/types'
import { formatValue } from '../../charts/format'
import { dateLabel } from '../../lib/labels'

/** 'Sales + Payments · Own period: yesterday vs the day before · Create Date', 'Dates: Create Date'. */
export function chartCaption(chart: ChartMeta, result: ChartResult | undefined, source: string): string {
  const own = chart.period?.mode && chart.period.mode !== 'dashboard' ? result?.period_label || chart.period.label : ''
  const shown = own ? own + (chart.date_column ? ` · ${dateLabel(chart.date_column)}` : '') : `Dates: ${dateLabel(chart.date_column)}`
  return source ? `${source} · ${shown}` : shown
}

/** The cubes of a chart, named once ('Bookings + Payments'), when the reader needs to know them. */
export function chartSource(chart: ChartMeta, severalCubes: boolean, cubeLabel: (cube: string) => string): string {
  return severalCubes || chart.cubes.length > 1 ? chart.cubes.map(cubeLabel).join(' + ') : ''
}

/** The first number of a table, for a headline without the server's text. */
export function firstNumber(table: Table | null | undefined): number | null {
  if (!table?.rows.length) return null
  const i = table.columns.findIndex((c) => c.type === 'number')
  const value = i >= 0 ? table.rows[0][i] : null
  return typeof value === 'number' ? value : null
}

export function headlineText(result: ChartResult | undefined): string {
  if (!result) return ''
  if (result.kpi?.text) return result.kpi.text
  return formatValue(result.kpi?.value ?? firstNumber(result.table))
}
