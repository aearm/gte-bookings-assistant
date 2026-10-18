/* eslint-disable @typescript-eslint/no-explicit-any -- ECharts options are free-form JSON */
// Draws one chart from the server's ECharts option (chart_options.py). The x-* keys of the option
// (x-format, x-label, x-tooltip, x-app ...) are turned into ECharts formatters (prepare.ts).
// Props are fixed: other pages rely on them. ECharts itself loads in its own file (EChartImpl).
import { lazy, memo, Suspense } from 'react'

export type EChartProps = { option: Record<string, any>; height?: number; dark?: boolean; testId?: string }

export const DEFAULT_HEIGHT = 330

const load = () => import('./EChartImpl')
const Impl = lazy(load)

/** Starts loading ECharts before the first chart needs it (pages with charts call this early). */
export function preloadECharts(): void {
  void load()
}

/** The height a chart is drawn at: the one asked for, or more when the chart needs it (x-app.height). */
export function chartHeight(option: Record<string, any> | null | undefined, height?: number): number {
  const least = option?.['x-app']?.height
  return Math.max(height ?? DEFAULT_HEIGHT, typeof least === 'number' ? least : 0)
}

function EChart({ option, height, dark, testId }: EChartProps) {
  if (!option) return null
  const id = testId ?? 'echart'
  if (option['x-app']?.kind === 'plotly') {
    return (
      <div className="chart-note chart-note--legacy" data-testid={id} data-kind="plotly">
        This chart was made with the old app; open Edit to redraw it.
      </div>
    )
  }
  const h = chartHeight(option, height)
  return (
    <Suspense fallback={<div className="echart-placeholder" style={{ height: h }} data-testid={id} aria-busy="true" />}>
      <Impl option={option} height={h} dark={dark} testId={id} />
    </Suspense>
  )
}

export default memo(EChart)
