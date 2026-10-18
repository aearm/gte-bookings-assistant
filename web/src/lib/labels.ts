// Words the dashboards use, as the Streamlit app wrote them (charts.TYPE_LABELS, dashboards.date_label).
import type { Info } from '../api/types'

export const CHART_TYPE_LABELS: Record<string, string> = {
  auto: 'Best fit (automatic)', kpi: 'Headline number',
  bar: 'Columns', horizontal_bar: 'Bars (rankings)', stacked_bar: 'Stacked columns',
  line: 'Line (trend over time)', area: 'Area (trend over time)', donut: 'Donut (share of a whole)',
  treemap: 'Treemap (share, many parts)', map: 'World map (countries)',
  heatmap: 'Heatmap (two breakdowns)', scatter: 'Scatter (two numbers)', table: 'Table',
  custom: 'Custom (describe it in words)',
}

export const chartTypeOptions = (allowAuto: boolean) =>
  Object.entries(CHART_TYPE_LABELS).filter(([v]) => allowAuto || v !== 'auto').map(([value, label]) => ({ value, label }))

export const AUTO_DATE = 'auto' // each cube's main date

/** "'Create Date'[Create Date]" -> "Create Date", "'Calendar'[Date]" -> "Calendar · Date". */
export function dateLabel(column: string | null | undefined): string {
  if (!column) return 'All dates'
  if (column === AUTO_DATE) return "Each cube's main date"
  const m = /^'([^']+)'\[([^\]]+)\]$/.exec(column)
  if (!m) return column.replace(/^"|"$/g, '')
  const [, table, name] = m
  const t = table.toLowerCase(), c = name.toLowerCase()
  return c.includes(t) || t.includes(c) ? name : `${table} · ${name}`
}

export const PERIOD_MODES = [
  { value: 'dashboard', label: "Follow the dashboard's period" },
  { value: 'own', label: 'Own period (moves forward every day)' },
  { value: 'fixed', label: 'Fixed dates (never move)' },
] as const

export const PERIOD_MODE_HELP = "Follow the dashboard: the period picked at the top. Own period: the chart's own dates, " +
  'worked out again every day (yesterday stays yesterday). Fixed dates: never move.'

/** The name of a cube as the app shows it (from /api/info scopes). */
export function cubeLabeller(info: Info | undefined): (cube: string) => string {
  const names = new Map((info?.scopes ?? []).filter((s) => s.value).map((s) => [s.value, s.label]))
  return (cube: string) => names.get(cube) ?? cube
}
