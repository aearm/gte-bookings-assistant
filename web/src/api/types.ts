// The shapes of docs/api.md. Keep in step with the server (server/schemas.py).

export type Column = {
  name: string; type: 'number' | 'text' | 'date'
  /** How the server writes this column's numbers (AED 4.5M, 12.3%...): the chart's format for it. */
  format?: import('../charts/format').XFormat | null
}
export type Table = { columns: Column[]; rows: unknown[][]; row_count: number; truncated: boolean }
export type Chart = { kind: string; option: Record<string, any> | null; title: string; summary: string; note: string }
export type Period = { start: string; end: string; label: string; preset: string }

export type Session = { admin: boolean; has_admin_password: boolean }
export type Info = {
  version: string; data_source: string; ready: boolean; why: string
  scopes: { value: string; label: string }[]; example_questions: string[]
  defaults: { preset: string; compare: string }
}

export type Turn = {
  id: string; question: string; understanding: string; query: string; cubes: string[]
  explanation: string; notes: string[]; periods: { phrase: string; start: string; end: string }[]
  table: Table | null; chart: Chart | null; clarify: { question: string; options: string[] } | null
  error: string | null; answer_id: number | null
}
export type Conversation = {
  id: string; scope: string; turns: Turn[]
  /** The question being answered right now and its progress so far (null when none is). */
  pending?: { question: string; steps: string[] } | null
}

export type PeriodMode = 'dashboard' | 'own' | 'fixed'
export type ChartMeta = {
  id: string; title: string; question: string; chart_type: string; width: 'half' | 'full'
  cubes: string[]; date_column: string; period: { mode: PeriodMode; label: string }; compares: boolean
  /** A headline number that is better when it falls (e.g. look-to-book): its change shows red when it rises. */
  lower_is_better?: boolean
}
export type DashboardSummary = { id: string; name: string; charts: number }
/** A filter above a dashboard's charts (e.g. a client); its values come from /dashboards/{id}/filters. */
export type FilterMeta = { key: string; label: string }
export type FilterChoices = FilterMeta & { options: { value: string; label: string }[]; default: string; error: string }
export type Dashboard = { id: string; name: string; charts: ChartMeta[]; filters?: FilterMeta[] }
export type ChartResult = {
  chart: Chart | null; table: Table | null; prev_table: Table | null
  kpi: { value: number | null; text: string; change: number | null; change_text: string } | null
  error: string | null; details: string | null; period_label: string
}
export type DashboardResults = {
  period: Period; compare: Period | null; data_as_of: { text: string; per_cube: Record<string, string> }
  charts: Record<string, ChartResult>; updating: boolean
  /** The value each filter had (its default when none was picked). */
  filters?: Record<string, string>
}
export type Periods = {
  presets: { name: string; start: string; end: string; label: string }[]
  compare_modes: { mode: string; label: string }[]; period: Period; compare: Period | null
}

export type Decision = {
  id: string; cube: string; question: string; why: string; options: string[]
  proposed: string; answer: string; status: 'proposed' | 'agreed'
}
export type Job = { id: string; kind: string; status: 'running' | 'done' | 'failed'; lines: string[]; error?: string }
