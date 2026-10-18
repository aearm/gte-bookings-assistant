// One chart on a dashboard: its title, a caption (cubes · dates · its own period), the chart or
// table, notes, and errors with their details. Drawn again only when its own data changes.
import { memo } from 'react'
import { Skeleton, Tooltip } from '@mantine/core'
import type { ChartMeta, ChartResult } from '../../api/types'
import EChart from '../../charts/EChart'
import DataTable from '../DataTable'
import ErrorNote from '../ErrorNote'
import ChartMenu, { type CardAction } from './ChartMenu'
import { chartCaption } from './cardText'

export const CHART_HEIGHT = 330

type Props = {
  chart: ChartMeta; result: ChartResult | undefined; source: string; isAdmin: boolean; span: 1 | 2
  compareDates: string // the comparison's dates, for tables that show the change
  onAction: (action: CardAction) => void
}

function ChartCard({ chart, result, source, isAdmin, span, compareDates, onAction }: Props) {
  return (
    <div className={`card chart-card${span === 2 ? ' span-2' : ''}`} data-testid={`chart-${chart.id}`}>
      <div className="chart-card__head">
        <div style={{ minWidth: 0 }}>
          <div className="chart-card__title">{chart.title}</div>
          <Tooltip label={chart.question} disabled={!chart.question} position="top-start">
            <div className="chart-caption">{chartCaption(chart, result, source)}</div>
          </Tooltip>
        </div>
        {isAdmin && <ChartMenu chart={chart} onAction={onAction} />}
      </div>
      <ChartBody result={result} compareDates={compareDates} />
    </div>
  )
}

function ChartBody({ result, compareDates }: { result: ChartResult | undefined; compareDates: string }) {
  if (!result) return <Skeleton height={CHART_HEIGHT} radius="md" />
  if (result.error) return <ErrorNote message={result.error} details={result.details} />
  const option = result.chart?.option
  const table = result.table
  const note = result.chart?.note || option?.['x-app']?.note || ''
  if (option) {
    return (
      <>
        <EChart option={option} height={CHART_HEIGHT} />
        {note && <div className="chart-note">{note}</div>}
      </>
    )
  }
  if (!table || !table.rows.length) return <div className="chart-empty">No data for this period.</div>
  return (
    <>
      <DataTable table={table} maxHeight={Math.min(CHART_HEIGHT, 38 + 35 * table.rows.length)} />
      {result.prev_table && compareDates && <div className="chart-note">Change vs {compareDates}.</div>}
      {note && <div className="chart-note">{note}</div>}
    </>
  )
}

export default memo(ChartCard)
