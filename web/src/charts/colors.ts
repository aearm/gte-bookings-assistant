// The chart colours of charts.py (light and dark) and the swap between them: the server builds an
// option for one theme (x-app.theme); when the page shows the other, every colour of the option is
// moved to its counterpart - palette for palette, ink for ink, a shade of a palette colour for the same
// shade of its dark twin, a point on the light-to-dark blue scale for the same point on the other scale.

export const PALETTE = {
  light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'],
  dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
}
export const SEQUENTIAL = {
  light: ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'],
  dark: ['#104281', '#184f95', '#256abf', '#3987e5', '#6da7ec', '#9ec5f4', '#cde2fb'],
}
export const INK = {
  light: { text: '#1d1d1f', muted: '#6e6e73', grid: '#e5e5ea', land: '#e8e8ed', surface: '#ffffff' },
  dark: { text: '#f5f5f7', muted: '#98989d', grid: '#38383a', land: '#2c2c2e', surface: '#1c1c1e' },
}
export const COMPARE_COLOR = { light: '#b8b8bf', dark: '#5c5c63' }

export type Theme = 'light' | 'dark'
type Rgb = [number, number, number]

const hex = (c: string): Rgb | null => {
  const m = /^#([0-9a-f]{6})$/i.exec(c.trim())
  if (!m) return null
  const n = parseInt(m[1], 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}
const toHex = (rgb: number[]): string => '#' + rgb.map((v) => Math.round(Math.min(255, Math.max(0, v))).toString(16).padStart(2, '0')).join('')

/** `color` moved `amount` (0-1) of the way toward another colour (charts._shade). */
export function shade(color: string, toward: string, amount: number): string {
  const a = hex(color)!, b = hex(toward)!
  return toHex(a.map((p, i) => p + (b[i] - p) * amount))
}

/** The colour at t (0-1) along a scale of stops. */
export function blend(stops: string[], t: number): string {
  const x = Math.min(Math.max(t, 0), 1) * (stops.length - 1)
  const i = Math.min(Math.floor(x), stops.length - 2)
  return shade(stops[i], stops[i + 1], x - i)
}

/** Dark or white text, whichever reads on this colour (chart_options._ink_on). */
export function inkOn(color: string): string {
  const rgb = hex(color)
  if (!rgb) return '#ffffff'
  return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2] > 150 ? '#1d1d1f' : '#ffffff'
}

/** Where a colour lies on the segment a→b (t in 0-1), or null when it is not on it (±2 per channel). */
function onSegment(c: Rgb, a: Rgb, b: Rgb): number | null {
  let t: number | null = null, span = 0
  for (let i = 0; i < 3; i++) {
    const d = b[i] - a[i]
    if (Math.abs(d) > span) { span = Math.abs(d); t = (c[i] - a[i]) / d }
  }
  if (t === null || t < -0.01 || t > 1.01) return null
  const ok = [0, 1, 2].every((i) => Math.abs(a[i] + (b[i] - a[i]) * t! - c[i]) <= 2)
  return ok ? Math.min(1, Math.max(0, t)) : null
}

type Swap = { general: Map<string, string>; scale: Map<string, string> }

function exactMaps(from: Theme, to: Theme): Swap {
  const pairs = (a: string[], b: string[]) => new Map(a.map((c, i) => [c.toLowerCase(), b[i]] as [string, string]))
  const general = pairs(PALETTE[from], PALETTE[to])
  const inkFrom = INK[from], inkTo = INK[to]
  for (const k of ['text', 'muted', 'grid', 'land'] as const) general.set(inkFrom[k], inkTo[k])
  general.set(COMPARE_COLOR[from], COMPARE_COLOR[to])
  return { general, scale: pairs(SEQUENTIAL[from], SEQUENTIAL[to]) }
}

const MAPS = { light: exactMaps('light', 'dark'), dark: exactMaps('dark', 'light') }

export type SwapContext = {
  surface?: boolean // a background or border: the white of the light theme is then the dark surface, not text
  scale?: boolean // a stop of a colour scale (visualMap inRange): the blue scale before the palette
}

/** A colour of a `from` option as it is drawn in the `to` theme. (In the dark theme one blue is both
 * the first palette colour and the middle of the scale: the context says which.) */
export function swapColor(color: string, from: Theme, to: Theme, context: SwapContext = {}): string {
  if (from === to || typeof color !== 'string') return color
  const key = color.trim().toLowerCase()
  if (key === INK[from].surface) return context.surface ? INK[to].surface : color
  const { general, scale } = MAPS[from]
  const exact = context.scale ? scale.get(key) ?? general.get(key) : general.get(key) ?? scale.get(key)
  if (exact) return exact
  const rgb = hex(key)
  if (!rgb) return color
  // a shade of a palette colour toward the background (one chart: a day per shade)
  const surface = hex(INK[from].surface)!
  for (let i = 0; i < PALETTE[from].length; i++) {
    const t = onSegment(rgb, hex(PALETTE[from][i])!, surface)
    if (t !== null) return shade(PALETTE[to][i], INK[to].surface, t)
  }
  // a point between two stops of the blue scale (treemap tiles)
  const stops = SEQUENTIAL[from]
  for (let i = 0; i < stops.length - 1; i++) {
    const t = onSegment(rgb, hex(stops[i])!, hex(stops[i + 1])!)
    if (t !== null) return blend(SEQUENTIAL[to], (i + t) / (stops.length - 1))
  }
  return color
}
