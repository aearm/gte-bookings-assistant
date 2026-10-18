/* eslint-disable @typescript-eslint/no-explicit-any -- ECharts options are free-form JSON */
// The server's options (built by chart_options.py from made-up data: __fixtures__/options.json) are
// turned into working ECharts options: formatters, theme colours, legends, maps. Each one is then drawn
// by ECharts itself (server-side SVG) to catch options it refuses.
import { describe, expect, it } from 'vitest'
import { use as registerParts, init, registerMap } from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'
import { feature } from 'topojson-client'
import fixturesText from './__fixtures__/options.json?raw'
import atlasText from 'world-atlas/countries-110m.json?raw'
import './echartsCore'
import './echartsExtra'
import { PALETTE, INK, SEQUENTIAL, swapColor } from './colors'
import { asArray, prepareOption } from './prepare'
import { countryName, toWorldGeoJson } from './worldMap'

registerParts([SVGRenderer])
const OPTIONS: Record<string, any> = JSON.parse(fixturesText)
const atlas = JSON.parse(atlasText)
registerMap('world', toWorldGeoJson(feature(atlas, atlas.objects.countries) as any) as any)

const prep = (name: string, dark = false) => prepareOption(OPTIONS[name], { dark, countryName })

function draw(option: Record<string, any>): string {
  const chart = init(null as unknown as HTMLElement, undefined, { renderer: 'svg', ssr: true, width: 800, height: 420 })
  try {
    chart.setOption(option)
    return chart.renderToSVGString()
  } finally {
    chart.dispose()
  }
}

describe('every kind of chart draws', () => {
  it.each(Object.keys(OPTIONS).filter((k) => k !== 'plotly'))('%s (light and dark)', (name) => {
    for (const dark of [false, true]) {
      const svg = draw(prep(name, dark).option)
      expect(svg.startsWith('<svg')).toBe(true)
    }
  })
})

describe('x-format on axes, series and scales', () => {
  it('axis labels and the axis pointer use the axis format', () => {
    const { option } = prep('bar')
    expect(option.yAxis.axisLabel.formatter(4_500_000)).toBe('AED 4.5M')
    expect(option.yAxis.axisPointer.label.formatter({ value: 1_250_000 })).toBe('AED 1.3M')
    expect(draw(option)).toContain('AED 4M')
  })

  it('a time axis of whole days steps by day', () => {
    const { option } = prep('compare_line')
    expect(option.xAxis.minInterval).toBe(86_400_000)
    expect(draw(option)).toMatch(/>1 Oct<[\s\S]*>2 Oct<[\s\S]*>3 Oct</)
  })

  it('tooltips write the series value in its format', () => {
    const bar = prep('bar').option.series[0]
    expect(bar.tooltip.valueFormatter(4_500_000, 0)).toBe('AED 4.5M')
    const scale = prep('heatmap').option.visualMap[0]
    expect(scale.formatter(22)).toBe('22')
  })

  it('the comparison: the change after the value, the other date over time', () => {
    const { option } = prep('compare_bar')
    const current = option.series.find((s: any) => s['x-change'])
    const rows = option.dataset[0].source
    const coral = rows.findIndex((r: unknown[]) => r[0] === 'Coral Bay')
    expect(current.tooltip.valueFormatter(4_500_000, coral)).toBe('AED 4.5M (+12.5%)')
    const lotus = rows.findIndex((r: unknown[]) => r[0] === 'Lotus')
    expect(current.tooltip.valueFormatter(2_000_000, lotus)).toBe('AED 2M') // nothing to compare with
    const line = prep('compare_line').option
    const dotted = line.series.find((s: any) => s['x-when'])
    expect(dotted.tooltip.valueFormatter(1.5, 0)).toBe('2 (2025-10-01)')
    const solid = line.series.find((s: any) => s['x-change'])
    expect(solid.tooltip.valueFormatter(1, 0)).toBe('1 (-33.3%)')
  })
})

describe('x-label and x-tooltip templates', () => {
  it('bar labels show the formatted value of the row', () => {
    const { option } = prep('bar')
    const dims = option.dataset[0].dimensions.map((d: any) => d.name)
    const params = { value: ['Coral Bay', 4_500_000], dimensionNames: dims, name: 'Coral Bay' }
    expect(option.series[0].label.formatter(params)).toBe('AED 4.5M')
  })

  it('donut labels show the share and tooltips are HTML-escaped', () => {
    const pie = prep('donut').option.series[0]
    const params = { value: ['Desert <b>Pearl</b>', 0.2], dimensionNames: ['Customer', 'Margin'], name: 'Desert <b>Pearl</b>', percent: 36.4 }
    expect(pie.label.formatter(params)).toBe('36.4%\n20.0%')
    expect(pie.tooltip.formatter(params)).toBe('Desert &lt;b&gt;Pearl&lt;/b&gt;<br>20.0%<br>36.4%')
  })

  it('heatmap and scatter templates read other columns of the row', () => {
    const cells = prep('heatmap').option.series[0]
    const params = { value: ['2026-08', 'API', 11], dimensionNames: ['Month', 'Channel', 'Bookings'] }
    expect(cells.tooltip.formatter(params)).toBe('API · 2026-08<br>11')
    const dots = prep('scatter').option.series[0]
    expect(dots.tooltip.formatter({ value: [2, 180], dimensionNames: ['Nights', 'Sales'] })).toBe('Nights: 2<br>Sales: 180')
  })

  it('treemap labels use inline values', () => {
    const tiles = prep('treemap').option.series[0]
    expect(tiles.label.formatter({ name: 'North', value: 4321 })).toBe('North\n4,321')
  })

  it('maps name countries as the result spells them, or by the atlas', () => {
    const { option, needsMap, height, mapExclude } = prep('map')
    const world = option.series[0]
    expect(needsMap && height === 420 && mapExclude[0] === 'ATA').toBe(true)
    expect(typeof world.projection.project).toBe('function')
    const [x, y] = world.projection.project([10, 50])
    expect(world.projection.unproject([x, y]).map((v: number) => Math.round(v * 1000) / 1000)).toEqual([10, 50])
    const row = { value: ['Spain', 'ESP', 80], dimensionNames: ['Destination Country', '_iso', 'Bookings'], name: 'ESP' }
    expect(world.tooltip.formatter(row)).toBe('Spain<br>80')
    expect(world.tooltip.formatter({ name: 'DEU', value: NaN })).toBe('Germany<br>-')
  })
})

describe('legend of one chart with an axis per measure', () => {
  it('one line per measure, named once, coloured like its axis', () => {
    const { option } = prep('one_chart')
    const legends = asArray(option.legend)
    expect(legends).toHaveLength(3)
    expect(legends[0].data).toEqual(['Requests · 2026-10-14', 'Requests · 2026-10-15'])
    expect(legends[0].formatter('Requests · 2026-10-14')).toBe('2026-10-14')
    const titles = asArray(option.title).map((t: any) => t.text)
    expect(titles).toEqual(['Requests', 'Bookings', 'Sales'])
    expect(asArray(option.title)[0].textStyle.color).toBe(PALETTE.light[0])
  })
})

describe('dark mode', () => {
  it('moves every colour to its dark counterpart', () => {
    const light = prep('bar').option
    const dark = prep('bar', true).option
    expect(light.color).toEqual(PALETTE.light)
    expect(dark.color).toEqual(PALETTE.dark)
    expect(dark.tooltip.backgroundColor).toBe(INK.dark.surface)
    expect(dark.yAxis.splitLine.lineStyle.color).toBe(INK.dark.grid)
    expect(prep('dark_bar', false).option.color).toEqual(PALETTE.light) // built dark, shown light
    expect(prep('map', true).option.visualMap[0].inRange.color).toEqual(SEQUENTIAL.dark)
  })

  it('shades and blends follow too', () => {
    expect(swapColor('#ffffff', 'light', 'dark')).toBe('#ffffff') // white text stays white
    expect(swapColor('#ffffff', 'light', 'dark', { surface: true })).toBe(INK.dark.surface) // a white border becomes the surface
    const pale = prep('one_chart').option.series[0].itemStyle.color
    const darkPale = prep('one_chart', true).option.series[0].itemStyle.color
    expect(pale).not.toBe(PALETTE.light[0])
    expect(darkPale).not.toBe(pale)
    const tiles = prep('treemap', true).option.series[0].data
    expect(tiles[0].label.color === '#ffffff' || tiles[0].label.color === '#1d1d1f').toBe(true)
  })
})

describe('what an option needs loaded', () => {
  it('extra chart types only for charts described in words', () => {
    expect(prep('bar').needsExtra).toBe(false)
    expect(prep('custom_sunburst').needsExtra).toBe(true)
    expect(prep('custom_funnel').needsExtra).toBe(true)
    expect(prep('panels').height).toBeGreaterThanOrEqual(525)
  })
})
