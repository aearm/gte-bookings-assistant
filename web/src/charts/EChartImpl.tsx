// The ECharts instance behind <EChart>: created once per chart, resized with its box, given a new
// option only when the option (or the theme) changes, and disposed when the chart goes away.
import { useEffect, useMemo, useRef, useState } from 'react'
import { useComputedColorScheme } from '@mantine/core'
import { getMap, init, registerMap, type ECharts } from './echartsCore'
import { prepareOption } from './prepare'
import { countryName, ensureWorldMap } from './worldMap'
import type { EChartProps } from './EChart'

let extra: Promise<unknown> | null = null
const loadExtra = () => (extra ??= import('./echartsExtra'))

export default function EChartImpl({ option, height, dark, testId }: EChartProps) {
  const box = useRef<HTMLDivElement>(null)
  const chart = useRef<ECharts | null>(null)
  const scheme = useComputedColorScheme('light', { getInitialValueInEffect: false })
  const isDark = dark ?? scheme === 'dark'
  const prepared = useMemo(() => prepareOption(option, { dark: isDark, countryName }), [option, isDark])
  const [problem, setProblem] = useState('')

  useEffect(() => {
    const el = box.current!
    const instance = init(el, undefined, { renderer: 'canvas' })
    chart.current = instance
    let frame = 0
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => !instance.isDisposed() && instance.resize())
    })
    observer.observe(el)
    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
      instance.dispose()
      chart.current = null
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const waits: Promise<unknown>[] = []
    if (prepared.needsMap && !getMap('world')) waits.push(ensureWorldMap(registerMap, prepared.mapExclude))
    if (prepared.needsExtra) waits.push(loadExtra())
    const draw = () => {
      const instance = chart.current
      if (cancelled || !instance || instance.isDisposed()) return
      try {
        instance.setOption(prepared.option, { notMerge: true })
        setProblem('')
      } catch (error) {
        setProblem(error instanceof Error ? error.message : String(error))
      }
    }
    if (waits.length) {
      Promise.all(waits).then(draw, (error) => !cancelled && setProblem(`The map could not be loaded: ${error}`))
    } else {
      draw()
    }
    return () => { cancelled = true }
  }, [prepared])

  return (
    <div className="echart" data-testid={testId} data-kind={prepared.kind}>
      <div ref={box} style={{ height, width: '100%' }} />
      {problem && <div className="chart-note chart-note--error">This chart could not be drawn: {problem}</div>}
    </div>
  )
}
