// A table writes its numbers the way the server says each column is written (a margin as 5.0%, sales as
// AED 4.5M), unless the page gives formats of its own.
import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'
import { MantineProvider } from '@mantine/core'
import type { Table } from '../api/types'
import DataTable from './DataTable'

const table: Table = {
  columns: [
    { name: 'Agency', type: 'text', format: null },
    { name: 'Sales', type: 'number', format: { style: 'compact', decimals: null, thousands: true, prefix: 'AED ', suffix: '' } },
    { name: 'Share', type: 'number', format: { style: 'percent', decimals: 1, thousands: false, prefix: '', suffix: '' } },
    { name: 'Bookings', type: 'number' },
  ],
  rows: [['Atlas', 4512000, 0.8333, 1234]], row_count: 1, truncated: false,
}

const html = (props: Partial<Parameters<typeof DataTable>[0]> = {}) =>
  renderToString(<MantineProvider><DataTable table={table} {...props} /></MantineProvider>)

describe('DataTable', () => {
  it("writes each column's numbers in the format the server sent", () => {
    const out = html()
    expect(out).toContain('AED 4.5M')
    expect(out).toContain('83.3%')
    expect(out).toContain('1,234') // no format: plain, with thousands separators
    expect(out).not.toContain('0.8333')
  })

  it("the page's own formats win", () => {
    expect(html({ formats: { Share: { style: 'fixed', decimals: 2, thousands: false, prefix: '', suffix: '' } } }))
      .toContain('0.83')
  })
})
