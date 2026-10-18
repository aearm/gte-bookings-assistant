/* eslint-disable @typescript-eslint/no-explicit-any -- test data */
// The dashboard page drawn once (server-side, no browser) from saved data: headline numbers, chart
// cards, captions, tables, errors, the period and comparison buttons.
import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'
import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import fixturesText from '../../charts/__fixtures__/options.json?raw'
import type { Dashboard, DashboardResults, Info } from '../../api/types'
import DashboardPage from '../../pages/DashboardPage'
import { todayIso } from '../../lib/periods'
import { readCompare, readPeriod, resultsParams } from '../../lib/periodState'
import { resultsKey } from '../../lib/queries'

const OPTIONS = JSON.parse(fixturesText)
const info: Info = {
  version: '2.0.0', data_source: 'ssas', ready: true, why: '', example_questions: [],
  scopes: [{ value: '', label: 'All data' }, { value: 'Sales', label: 'Sales' }, { value: 'Payments', label: 'Payments' }],
  defaults: { preset: 'Last 7 days', compare: 'previous' },
}
const meta = (id: string, chart_type: string, extra: Record<string, any> = {}) => ({
  id, title: `Chart ${id}`, question: `Question ${id}`, chart_type, width: 'half' as const, cubes: ['Sales'],
  date_column: "'Create Date'[Create Date]", period: { mode: 'dashboard' as const, label: '' }, compares: true, ...extra,
})
const board: Dashboard = {
  id: 'd1', name: 'Sales overview',
  charts: [
    meta('k1', 'kpi'),
    meta('c1', 'bar', { cubes: ['Sales', 'Payments'] }),
    meta('c2', 'table', { period: { mode: 'own', label: 'Own period: yesterday vs the day before' } }),
    meta('c3', 'line', { width: 'full' }),
    meta('c4', 'custom'),
  ],
}
const table = { columns: [{ name: 'Customer', type: 'text' as const }, { name: 'Sales', type: 'number' as const }],
                rows: [['Atlas', 1250000], ['Coral Bay', 4500000.5]], row_count: 2, truncated: false }
const chart = (option: any, kind = 'bar') => ({ kind, option, title: '', summary: '', note: '' })
const results: DashboardResults = {
  period: { start: '2026-10-10', end: '2026-10-17', label: 'Last 7 days · 10 Oct – 16 Oct 2026 · W41–42', preset: 'Last 7 days' },
  compare: null, updating: true,
  data_as_of: { text: '16 Oct, 08:10', per_cube: { Sales: '16 Oct, 08:10', Payments: '16 Oct, 07:55' } },
  charts: {
    k1: { chart: null, table, prev_table: null, kpi: { value: 4512000, text: 'AED 4.5M', change: 0.125, change_text: '+12.5% vs the 7 days before' },
          error: null, details: null, period_label: '' },
    c1: { chart: chart(OPTIONS.bar), table, prev_table: null, kpi: null, error: null, details: null, period_label: '' },
    c2: { chart: chart(null, 'table'), table, prev_table: null, kpi: null, error: null, details: null,
          period_label: 'Own period: yesterday vs the day before (15–16 Oct)' },
    c3: { chart: null, table: null, prev_table: null, kpi: null, error: 'The cube server could not be reached.',
          details: 'Timeout after 30 s', period_label: '' },
    c4: { chart: chart(OPTIONS.plotly, 'plotly'), table, prev_table: null, kpi: null, error: null, details: null, period_label: '' },
  },
}

function render(admin: boolean): string {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  client.setQueryData(['session'], { admin, has_admin_password: true })
  client.setQueryData(['info'], info)
  client.setQueryData(['dashboards'], [{ id: 'd1', name: 'Sales overview', charts: 5 }])
  client.setQueryData(['dashboard', 'd1'], board)
  const params = resultsParams(readPeriod(new URLSearchParams(''), info.defaults, todayIso()),
                               readCompare(new URLSearchParams(''), info.defaults))
  client.setQueryData(resultsKey('d1', params), results)
  return renderToString(
    <MantineProvider>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/dashboard/d1']}>
          <Routes><Route path="/dashboard/:id" element={<DashboardPage />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  )
}

describe('DashboardPage', () => {
  const html = render(true)

  it('shows the title, the period and the comparison', () => {
    expect(html).toContain('Sales overview')
    expect(html).toMatch(/Last 7 days · \d+ \w+ – \d+ \w+ \d{4} · W\d+/)
    expect(html).toMatch(/vs \d+ \w+ – \d+ \w+ \d{4}/)
    expect(html).toContain('Data updated 16 Oct, 08:10')
    expect(html).toContain('Showing the last numbers while the latest load…')
  })

  it('shows headline numbers with their change', () => {
    expect(html).toContain('AED 4.5M')
    expect(html).toContain('+12.5% vs the 7 days before')
    expect(html).toContain('kpi-change up')
  })

  it('captions name the cubes, dates and own periods', () => {
    expect(html).toContain('Sales + Payments · Dates: Create Date')
    expect(html).toContain('Own period: yesterday vs the day before (15–16 Oct) · Create Date')
  })

  it('draws tables, errors and old charts', () => {
    expect(html).toContain('4,500,001') // table numbers with thousands
    expect(html).toContain('The cube server could not be reached.')
    expect(html).toContain('Technical details (for support)')
    expect(html).toContain('This chart was made with the old app; open Edit to redraw it.')
    expect(html).toContain('data-testid="echart"') // the chart's place while ECharts loads
  })

  it('shows chart menus to admins only', () => {
    expect(html).toContain('chart-menu-c1')
    expect(render(false)).not.toContain('chart-menu-c1')
  })
})
