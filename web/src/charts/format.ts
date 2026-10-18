// Numbers written the way the server's chart options describe them ("x-format"). A port of
// chart_options.format_value / describe_format: the same value and format must give the same text
// in the browser as in Python (tests in format.test.ts are the Python examples).

export type XFormat = {
  style?: 'fixed' | 'percent' | 'compact' | 'auto' | string
  decimals?: number | null
  thousands?: boolean
  sign?: boolean
  trim?: boolean
  prefix?: string
  suffix?: string
}

export const AUTO: Required<XFormat> = {
  style: 'auto', decimals: null, thousands: true, sign: false, trim: true, prefix: '', suffix: '',
}

const UNITS: [number, string][] = [[1e9, 'B'], [1e6, 'M'], [1e3, 'k'], [1, '']]

/** `number` (>= 0) with `places` decimals, halves rounded up on the exact binary value (as Python's
 * Decimal(number).quantize(ROUND_HALF_UP)); "," between thousands; trailing zeros dropped on request. */
export function fixed(number: number, places: number, thousands: boolean, trimZeros: boolean): string {
  // toFixed works on the exact value of the double and picks the larger neighbour on a tie: for
  // numbers >= 0 that is ROUND_HALF_UP. Above 1e21 it switches to exponents; such doubles are whole.
  let text = number < 1e21 ? number.toFixed(places)
    : BigInt(number).toString() + (places > 0 ? '.' + '0'.repeat(places) : '')
  if (thousands) {
    const [whole, part] = text.split('.')
    text = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (part !== undefined ? '.' + part : '')
  }
  if (trimZeros && text.includes('.')) text = text.replace(/0+$/, '').replace(/\.$/, '')
  return text
}

/** `size` (>= 0) in k / M / B; a value that rounds up to 1,000 of a unit moves to the next one. */
function compact(size: number, decimals: number | null | undefined, thousands: boolean, trimZeros: boolean): string {
  let k = UNITS.findIndex(([step, unit]) => size >= step || !unit)
  for (;;) {
    const [step, unit] = UNITS[k]
    const scaled = size / step
    let places: number
    if (decimals !== null && decimals !== undefined) places = decimals
    else if (unit) places = scaled < 100 ? 1 : 0
    else places = Number.isInteger(size) ? 0 : 2
    const text = fixed(scaled, places, thousands, trimZeros)
    if (k > 0 && Number(text.replace(/,/g, '')) >= 1000) {
      k -= 1
      continue
    }
    return text + unit
  }
}

/** A value written the way its format describes: 'AED 4.5M', '12.3%', '+12.5%', '1,234'; '-' when
 * missing; text as it is. */
export function formatValue(value: unknown, format?: XFormat | null): string {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'boolean') return value ? 'True' : 'False'
  if (typeof value !== 'number') return String(value)
  if (!Number.isFinite(value)) return '-'
  const fmt = { ...AUTO, ...(format ?? {}) }
  const style = fmt.style || 'auto'
  const size = Math.abs(value)
  const thousands = !!fmt.thousands
  let body: string
  if (style === 'percent') body = fixed(size * 100, fmt.decimals || 0, thousands, !!fmt.trim) + '%'
  else if (style === 'compact') body = compact(size, fmt.decimals, thousands, !!fmt.trim)
  else if (style === 'fixed') body = fixed(size, fmt.decimals || 0, thousands, !!fmt.trim)
  else if (size >= 1e6) body = compact(size, null, thousands, true)
  else body = fixed(size, size >= 1000 || Number.isInteger(value) ? 0 : 2, thousands, false)
  const sign = value < 0 && /[1-9]/.test(body) ? '-' : fmt.sign ? '+' : ''
  return `${fmt.prefix || ''}${sign}${body}${fmt.suffix || ''}`
}

const D3 = /^(?:.?[<>=^])?([-+( ])?([$#])?0?(\d+)?(,)?(?:\.(\d+))?(~)?([a-zA-Z%])?$/
const STYLES: Record<string, XFormat['style']> = { f: 'fixed', d: 'fixed', '%': 'percent', s: 'compact' }

/** The format description for a d3 format (",.0f", ".1%", "~s", "$,.0f") and a prefix / suffix, as
 * chart_options.describe_format. Unknown formats keep the prefix and suffix and write numbers 'auto'. */
export function describeFormat(d3 = '', prefix = '', suffix = ''): Required<XFormat> {
  const fmt = { ...AUTO, prefix: prefix || '', suffix: suffix || '' }
  const match = D3.exec((d3 || '').trim())
  const style = match && d3 ? STYLES[match[7] ?? ''] : undefined
  if (!match || !style) return fmt
  const [, sign, symbol, , comma, precision, tilde, kind] = match
  if (symbol === '$' && !fmt.prefix) fmt.prefix = '$'
  const decimals = style === 'compact' ? null : kind === 'd' || precision === undefined ? 0 : Number(precision)
  return { ...fmt, style, decimals, thousands: !!comma, sign: sign === '+', trim: !!tilde }
}

/** A formatter function for an x-format (what ECharts' formatters are given). */
export function formatterFor(format: XFormat | null | undefined): (value: unknown) => string {
  return (value: unknown) => formatValue(value, format)
}

/** A whole-number or 2-decimal number with thousands separators, for tables without a format. */
const WHOLE = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const TWO = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 })
export function plainNumber(value: number): string {
  if (!Number.isFinite(value)) return '-'
  return (Number.isInteger(value) || Math.abs(value) >= 1000 ? WHOLE : TWO).format(value)
}
