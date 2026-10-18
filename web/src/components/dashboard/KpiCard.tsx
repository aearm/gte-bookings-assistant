// A headline number: the value for the period and its change against the comparison.
import { memo } from 'react'
import { Skeleton, Tooltip } from '@mantine/core'
import type { ChartMeta, ChartResult } from '../../api/types'
import ErrorNote from '../ErrorNote'
import ChartMenu, { type CardAction } from './ChartMenu'
import { headlineText } from './cardText'

type Props = {
  chart: ChartMeta; result: ChartResult | undefined; source: string; isAdmin: boolean
  onAction: (action: CardAction) => void
}

function KpiCard({ chart, result, source, isAdmin, onAction }: Props) {
  const own = chart.period?.mode !== 'dashboard' ? result?.period_label || chart.period?.label : ''
  const change = result?.kpi?.change
  const good = typeof change === 'number' && (chart.lower_is_better ? change < 0 : change > 0)
  const direction = typeof change !== 'number' || change === 0 ? 'flat' : good ? 'up' : 'down'
  const help = [chart.question, source].filter(Boolean).join(' · ')
  return (
    <div className="card kpi" data-testid={`kpi-${chart.id}`}>
      {isAdmin && <div style={{ position: 'absolute', top: 10, right: 10 }}><ChartMenu chart={chart} onAction={onAction} /></div>}
      <Tooltip label={help} disabled={!help} position="top-start">
        <div className="kpi-title">{chart.title}</div>
      </Tooltip>
      {!result ? (
        <Skeleton height={36} width="60%" mt={8} radius="md" />
      ) : result.error ? (
        <div style={{ marginTop: 8 }}><ErrorNote message={result.error} details={result.details} /></div>
      ) : (
        <>
          <div className="kpi-value">{headlineText(result)}</div>
          {result.kpi?.change_text && <div className={`kpi-change ${direction}`}>{result.kpi.change_text}</div>}
        </>
      )}
      {own && <div className="chart-note">{own}</div>}
    </div>
  )
}

export default memo(KpiCard)
