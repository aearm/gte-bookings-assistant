// formatValue must write what chart_options.format_value writes (tests/test_chart_options.py).
import { describe, expect, it } from 'vitest'
import { AUTO, describeFormat as D, formatValue, formatterFor, plainNumber } from './format'

describe('formatValue', () => {
  it.each([
    [4_512_000, '~s', 'AED ', '', 'AED 4.5M'],
    [1_260_000_000, '~s', '', '', '1.3B'],
    [0.1234, '.1%', '', '', '12.3%'],
    [12.345, ',.1f', '', '%', '12.3%'],
    [1234.4, ',.0f', '', '', '1,234'],
    [3.14159, ',.2f', '', '', '3.14'],
    [null, '', '', '', '-'],
  ])('reads like the headline numbers: %s with "%s"', (value, d3, prefix, suffix, text) => {
    expect(formatValue(value, D(d3, prefix, suffix))).toBe(text)
  })

  it.each([
    [2_000_000, D('~s'), '2M'], [2_000_000, D('s'), '2.0M'], [125_000, D('~s'), '125k'], [999_999, D('~s'), '1M'],
    [950, D('~s'), '950'], [-4_512_000, D('~s', 'AED '), 'AED -4.5M'], [12_500, D('~s'), '12.5k'],
    [0.125, D('+.1%'), '+12.5%'], [-0.05, D('+.1%'), '-5.0%'], [0.5, D('.0%'), '50%'], [12.3456, D('.2%'), '1234.56%'],
    [1234.5, D(',.0f'), '1,235'], [2.5, D(',.0f'), '3'], [0.125, D(',.2f'), '0.13'], [1234.5, D('.2f'), '1234.50'],
    [-0.001, D(',.2f'), '0.00'], [-1234.5, D(',.1f'), '-1,234.5'], [1234, D('$,.0f'), '$1,234'], [7, D(',d'), '7'],
    [1500, D(''), '1,500'], [0.125, D(''), '0.13'], [3, D(''), '3'], [40_000_000, D(''), '40M'],
    [12.0, D(',.1f', '', ' nights'), '12.0 nights'], [1.5, D('.2~f'), '1.5'],
    [NaN, D(',.0f'), '-'], [Infinity, D(',.0f'), '-'], ['Atlas', D(',.0f'), 'Atlas'],
  ])('%s -> %s', (value, fmt, text) => {
    expect(formatValue(value, fmt as ReturnType<typeof D>)).toBe(text)
  })

  it('writes plain numbers without a format, and odd values as text', () => {
    expect(formatValue(5)).toBe('5')
    expect(formatValue(5, null)).toBe('5')
    expect(formatValue(undefined)).toBe('-')
    expect(formatValue(true)).toBe('True')
    expect(formatValue(1234567.891, AUTO)).toBe('1.2M')
    expect(formatValue(1e22, D(',.0f'))).toBe('10,000,000,000,000,000,000,000')
  })
})

describe('describeFormat', () => {
  it('turns d3 formats into format descriptions', () => {
    expect(D(',.0f')).toEqual({ style: 'fixed', decimals: 0, thousands: true, sign: false, trim: false, prefix: '', suffix: '' })
    expect(D('~s', 'AED ')).toEqual({ style: 'compact', decimals: null, thousands: false, sign: false, trim: true,
                                      prefix: 'AED ', suffix: '' })
    expect([D('.1%').style, D('.1%').decimals, D('.1%').thousands]).toEqual(['percent', 1, false])
    expect(D('+.1%').sign && D(',.2f').decimals === 2 && D('.0%').decimals === 0).toBe(true)
    expect([D('').style, D('.3e').style, D('nonsense').style]).toEqual(['auto', 'auto', 'auto'])
    expect(D('.3e', '', ' s').suffix).toBe(' s')
  })
})

describe('x-format -> formatter', () => {
  it('gives ECharts a function writing each value in the format', () => {
    const axis = formatterFor({ style: 'compact', decimals: null, thousands: false, sign: false, trim: true, prefix: 'AED ', suffix: '' })
    expect([0, 500_000, 1_000_000, 4_500_000].map(axis)).toEqual(['AED 0', 'AED 500k', 'AED 1M', 'AED 4.5M'])
    expect(formatterFor(undefined)(1234.5)).toBe('1,235')
    expect(formatterFor({ style: 'percent', decimals: 1 })(0.1234)).toBe('12.3%') // missing keys as AUTO
  })

  it('writes table numbers plainly', () => {
    expect([plainNumber(1234), plainNumber(0.125), plainNumber(1234.567), plainNumber(-3.5)])
      .toEqual(['1,234', '0.13', '1,235', '-3.5'])
  })
})
