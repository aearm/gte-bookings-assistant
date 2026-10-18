/* eslint-disable @typescript-eslint/no-explicit-any -- ECharts options are free-form JSON */
// Turns the server's ECharts option (chart_options.py) into the option handed to ECharts: the x-* keys
// become formatter functions (JSON can't carry them), colours follow the page's theme, a legend of
// measures is grouped, and maps get their projection. Pure: no ECharts import, so it is unit-tested.
import { swapColor, inkOn, type Theme } from './colors'
import { describeFormat, formatValue, type XFormat } from './format'
import { NATURAL_EARTH } from './projection'

type Obj = Record<string, any>

export type Prepared = {
  option: Obj
  kind: string
  height: number | null // the least height the chart needs (x-app.height)
  needsMap: boolean // draws the "world" map (registered on first use)
  needsExtra: boolean // uses chart types or parts beyond the usual ones (described charts)
  mapExclude: string[]
}

const CORE_SERIES = new Set(['bar', 'line', 'pie', 'scatter', 'heatmap', 'treemap', 'map'])
const EXTRA_PARTS = ['polar', 'radiusAxis', 'angleAxis', 'radar', 'dataZoom', 'toolbox', 'brush', 'geo', 'parallel',
  'parallelAxis', 'singleAxis', 'calendar', 'timeline', 'graphic', 'aria', 'matrix']
const AXES = ['xAxis', 'yAxis', 'radiusAxis', 'angleAxis', 'singleAxis', 'parallelAxis']
const SURFACE_KEYS = new Set(['backgroundColor', 'borderColor'])
const SCALE_KEYS = new Set(['inRange', 'outOfRange'])
const PLACEHOLDER = /\{(value|name|percent|series|col:[^}]+)\}/g
const LEGEND_ROW = 24 // pixels per legend line when measures get a line each
const CHANGE_FORMAT = describeFormat('+.1%')

export const asArray = <T = Obj>(value: unknown): T[] =>
  Array.isArray(value) ? value as T[] : value && typeof value === 'object' ? [value as T] : []

const escapeHtml = (text: string): string =>
  text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')

/** A copy of the option, colours moved to the other theme when asked. Dataset rows (often thousands)
 * are shared, not copied: nothing here changes them. */
function copy(value: unknown, swap: [Theme, Theme] | null, key = '', scale = false): any {
  if (Array.isArray(value)) {
    if (key === 'source') return value
    return value.map((v) => copy(v, swap, key, scale))
  }
  if (value && typeof value === 'object') {
    const out: Obj = {}
    const inScale = scale || SCALE_KEYS.has(key)
    for (const [k, v] of Object.entries(value)) out[k] = copy(v, swap, k, inScale)
    return out
  }
  if (swap && typeof value === 'string' && /color$/i.test(key)) {
    return swapColor(value, swap[0], swap[1], { surface: SURFACE_KEYS.has(key), scale })
  }
  return value
}

type Context = {
  rootDims: string[]
  rootRows: unknown[][] | null
  formats: Record<string, XFormat>
  mapNames: Record<string, string> // ISO-3 code -> the country as the result spells it
  countryName: (code: string) => string | undefined // the atlas' own name (countries without data)
}

/** The value of a column in the row a callback was given (dataset rows arrive whole). */
function columnValue(params: Obj, column: string, ctx: Context): unknown {
  const row = Array.isArray(params.value) ? params.value : Array.isArray(params.data) ? params.data : null
  if (!row) return undefined
  const dims: string[] = Array.isArray(params.dimensionNames) && params.dimensionNames.length ? params.dimensionNames : ctx.rootDims
  const i = dims.indexOf(column)
  return i >= 0 ? row[i] : undefined
}

function seriesValue(params: Obj, series: Obj, ctx: Context): unknown {
  const column = series['x-value']
  if (column) {
    const found = columnValue(params, column, ctx)
    if (found !== undefined) return found
  }
  const value = params.value
  if (Array.isArray(value)) return value[value.length - 1]
  return value && typeof value === 'object' && 'value' in value ? (value as Obj).value : value
}

/** A label or tooltip template filled in for one item: {value} {name} {percent} {series} {col:Column}. */
export function fillTemplate(template: string, params: Obj, series: Obj, ctx: Context, html: boolean): string {
  const fmt: XFormat | undefined = series['x-format']
  const isMap = series.type === 'map'
  const place = (token: string): string => {
    if (token === 'value') return formatValue(seriesValue(params, series, ctx), fmt)
    if (token === 'name') {
      const name = params.name ?? ''
      return isMap ? ctx.mapNames[name] ?? ctx.countryName(name) ?? name : String(name)
    }
    if (token === 'percent') return typeof params.percent === 'number' ? `${params.percent.toFixed(1)}%` : ''
    if (token === 'series') return String(params.seriesName ?? '')
    const column = token.slice(4)
    const value = columnValue(params, column, ctx)
    if (value === undefined && isMap) return ctx.mapNames[params.name] ?? ctx.countryName(params.name) ?? String(params.name ?? '')
    if (value === null || value === undefined) return ''
    return ctx.formats[column] ? formatValue(value, ctx.formats[column]) : String(value)
  }
  const fill = (piece: string) => {
    let out = '', last = 0
    for (const m of piece.matchAll(PLACEHOLDER)) {
      const literal = piece.slice(last, m.index)
      out += html ? escapeHtml(literal) : literal
      const text = place(m[1])
      out += html ? escapeHtml(text) : text
      last = m.index! + m[0].length
    }
    const rest = piece.slice(last)
    return out + (html ? escapeHtml(rest) : rest)
  }
  return html ? template.split(/<br\s*\/?>/i).map(fill).join('<br>') : fill(template)
}

/** tooltip.valueFormatter of a series: its format, then the change against the comparison
 * (x-change, " (+12.5%)") and the comparison's own date (x-when, " (2025-01)"), read from the root
 * dataset's row at the hovered index. */
export function valueFormatterFor(series: Obj, ctx: Context) {
  const fmt: XFormat | undefined = series['x-format']
  const change: string | undefined = series['x-change']
  const when: string | undefined = series['x-when']
  const changeAt = change ? ctx.rootDims.indexOf(change) : -1
  const whenAt = when ? ctx.rootDims.indexOf(when) : -1
  const changeFormat = (change && ctx.formats[change]) || ctx.formats._change || CHANGE_FORMAT
  return (value: unknown, dataIndex?: number): string => {
    let text = Array.isArray(value) ? value.map((v) => formatValue(v, fmt)).join(' ') : formatValue(value, fmt)
    const row = ctx.rootRows && typeof dataIndex === 'number' ? ctx.rootRows[dataIndex] : null
    if (row && changeAt >= 0) {
      const c = row[changeAt]
      if (typeof c === 'number' && Number.isFinite(c)) text += ` (${formatValue(c, changeFormat)})`
    }
    if (row && whenAt >= 0) {
      const w = row[whenAt]
      if (w !== null && w !== undefined && w !== '') text += ` (${w})`
    }
    return text
  }
}

const DAY_MS = 86_400_000
const DAY_LABELS = { year: '{yyyy}', month: '{d} {MMM}', day: '{d} {MMM}' }

function formatAxes(option: Obj, wholeDays: boolean): void {
  for (const key of AXES) {
    for (const axis of asArray(option[key])) {
      if (axis.type === 'time' && wholeDays) { // days, not hours, on a short period: '1 Oct', '2 Oct'
        axis.minInterval ??= DAY_MS
        if (!axis.axisLabel?.formatter) axis.axisLabel = { ...axis.axisLabel, formatter: DAY_LABELS }
      }
      const fmt: XFormat | undefined = axis['x-format']
      if (!fmt) continue
      const write = (value: unknown) => formatValue(value, fmt)
      axis.axisLabel = { ...axis.axisLabel, formatter: write }
      const pointer = axis.axisPointer ?? {}
      axis.axisPointer = { ...pointer, label: { ...pointer.label, formatter: (p: Obj) => write(p.value) } }
    }
  }
  for (const map of asArray(option.visualMap)) {
    const fmt: XFormat | undefined = map['x-format']
    if (!fmt) continue
    map.formatter = (a: unknown, b?: unknown) =>
      b === undefined ? formatValue(a, fmt) : `${formatValue(a, fmt)} – ${formatValue(b, fmt)}`
  }
}

/** One legend line per measure ("Requests: 14 Oct, 15 Oct"), when one chart has an axis per measure
 * (series carry x-group) and the measures are broken down further. */
function groupLegend(option: Obj, series: Obj[]): void {
  const legend = option.legend
  if (!legend || Array.isArray(legend) || legend.show === false) return
  const groups = [...new Set(series.map((s) => s['x-group']).filter(Boolean))] as string[]
  const members = groups.map((g) => series.filter((s) => s['x-group'] === g).map((s) => String(s.name)))
  if (groups.length < 2 || members.every((m) => m.length < 2)) return
  const axes = asArray(option.yAxis)
  const titles = asArray(option.title)
  const lines = groups.length
  option.legend = groups.map((group, i) => {
    const bottom = (lines - 1 - i) * LEGEND_ROW
    const color = axes[i]?.nameTextStyle?.color ?? axes[i]?.axisLabel?.color ?? legend.textStyle?.color
    titles.push({ text: group, left: 0, bottom, padding: [6, 0, 0, 0],
                  textStyle: { fontSize: 12, fontWeight: 600, color } })
    const prefix = `${group} · `
    const rest: Obj = { ...legend }
    delete rest.top
    return { ...rest, data: members[i], bottom, left: 12 + group.length * 7.5,
             formatter: (name: string) => (name.startsWith(prefix) ? name.slice(prefix.length) : name) }
  })
  option.title = titles
  for (const grid of asArray(option.grid)) {
    if (typeof grid.bottom === 'number') grid.bottom += (lines - 1) * LEGEND_ROW
  }
}

/** True when the dataset's time columns hold dates without a time of day ('2026-10-01'). */
function wholeDays(root: Obj | undefined): boolean {
  const dims = asArray<Obj | string>(root?.dimensions)
  const rows = Array.isArray(root?.source) ? root.source as unknown[][] : []
  const times = dims.map((d, i) => (typeof d === 'object' && d?.type === 'time' ? i : -1)).filter((i) => i >= 0)
  if (!times.length || !rows.length) return false
  return rows.slice(0, 200).every((row) => times.every((i) => {
    const v = Array.isArray(row) ? row[i] : null
    return v === null || v === undefined || (typeof v === 'string' && v.length === 10)
  }))
}

export type PrepareOptions = {
  dark: boolean
  countryName?: (code: string) => string | undefined
}

export function prepareOption(source: Obj, { dark, countryName = () => undefined }: PrepareOptions): Prepared {
  const app: Obj = source?.['x-app'] ?? {}
  const built: Theme = app.theme === 'dark' ? 'dark' : 'light'
  const wanted: Theme = dark ? 'dark' : 'light'
  const option: Obj = copy(source, built === wanted ? null : [built, wanted])

  const root = asArray(option.dataset)[0]
  const rootDims: string[] = asArray<unknown>(root?.dimensions).map((d) =>
    typeof d === 'string' ? d : String((d as Obj)?.name ?? ''))
  const rootRows = Array.isArray(root?.source) && Array.isArray(root.source[0]) ? root.source as unknown[][] : null
  const mapApp = app.map ?? {}
  const mapNames: Record<string, string> = {}
  for (const [name, code] of Object.entries(mapApp.codes ?? {})) if (!(String(code) in mapNames)) mapNames[String(code)] = name
  const ctx: Context = { rootDims, rootRows, formats: app.formats ?? {}, mapNames, countryName }

  formatAxes(option, wholeDays(root))
  const series = asArray(option.series)
  let needsMap = false
  let needsExtra = EXTRA_PARTS.some((part) => part in option)
  for (const s of series) {
    const type = String(s.type ?? '')
    if (!CORE_SERIES.has(type) || s.markLine || s.markPoint || s.markArea) needsExtra = true
    if (s['x-format'] || s['x-change'] || s['x-when']) {
      s.tooltip = { ...s.tooltip, valueFormatter: valueFormatterFor(s, ctx) }
    }
    if (s['x-label'] && s.label) {
      const template = String(s['x-label'])
      s.label = { ...s.label, formatter: (p: Obj) => fillTemplate(template, p, s, ctx, false) }
    }
    if (s['x-tooltip']) {
      const template = String(s['x-tooltip'])
      s.tooltip = { ...s.tooltip, formatter: (p: Obj) => fillTemplate(template, p, s, ctx, true) }
    }
    if (type === 'map' && (s.map ?? 'world') === 'world') {
      needsMap = true
      s.projection ??= NATURAL_EARTH
    }
    if (type === 'treemap' && built !== wanted) recolourTreemapText(s.data)
  }
  groupLegend(option, series)

  const height = typeof app.height === 'number' && app.height > 0 ? app.height : null
  return { option, kind: String(app.kind ?? ''), height, needsMap, needsExtra,
           mapExclude: Array.isArray(mapApp.exclude) ? mapApp.exclude.map(String) : ['ATA'] }
}

/** Treemap tiles moved to the other theme: their text, dark or white, follows the new tile colour. */
function recolourTreemapText(nodes: unknown): void {
  for (const node of asArray(nodes)) {
    const tile = node.itemStyle?.color
    if (typeof tile === 'string') {
      const ink = inkOn(tile)
      if (node.label) node.label.color = ink
      if (node.upperLabel) node.upperLabel.color = ink
    }
    if (node.children) recolourTreemapText(node.children)
  }
}
