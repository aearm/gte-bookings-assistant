// A result table (the API's Table shape). Props are fixed: other pages rely on them (formats is an
// optional addition). Numbers are right-aligned with thousands separators; the header stays in view;
// a click on a column name sorts by it. Only the first 500 rows are drawn, with a note when there are more.
import { memo, useMemo, useState } from 'react'
import type { Column, Table } from '../api/types'
import { formatValue, plainNumber, type XFormat } from '../charts/format'

export type DataTableProps = { table: Table; maxHeight?: number; testId?: string; formats?: Record<string, XFormat> }

export const MAX_ROWS_SHOWN = 500

function cellText(value: unknown, column: Column, format?: XFormat): string {
  if (value === null || value === undefined || value === '') return ''
  const shown = format ?? column.format ?? undefined // the page's own format, else the one the server sent
  if (typeof value === 'number') return shown ? formatValue(value, shown) : plainNumber(value)
  if (column.type === 'date' && typeof value === 'string') return value.replace('T', ' ').replace(/(:\d\d)(:00)?(\.\d+)?$/, '$1')
  return String(value)
}

function compare(a: unknown, b: unknown): number {
  if (a === b) return 0
  if (a === null || a === undefined) return 1 // empty cells last
  if (b === null || b === undefined) return -1
  if (typeof a === 'number' && typeof b === 'number') return a - b
  return String(a).localeCompare(String(b), undefined, { numeric: true })
}

function DataTable({ table, maxHeight, testId, formats }: DataTableProps) {
  const [sort, setSort] = useState<{ column: number; descending: boolean } | null>(null)
  const rows = useMemo(() => {
    if (!sort) return table.rows.slice(0, MAX_ROWS_SHOWN)
    const sorted = [...table.rows].sort((x, y) => compare(x[sort.column], y[sort.column]))
    if (sort.descending) sorted.reverse()
    return sorted.slice(0, MAX_ROWS_SHOWN)
  }, [table.rows, sort])

  const total = Math.max(table.row_count ?? table.rows.length, table.rows.length)
  const numeric = table.columns.map((c) => c.type === 'number')
  const toggle = (column: number) =>
    setSort((s) => (s?.column === column ? (s.descending ? null : { column, descending: true }) : { column, descending: false }))

  return (
    <div data-testid={testId ?? 'datatable'}>
      <div className="dt-wrap" style={{ maxHeight: maxHeight ?? 400 }}>
        <table className="dt">
          <thead>
            <tr>
              {table.columns.map((c, i) => (
                <th key={i} className={numeric[i] ? 'num' : undefined} onClick={() => toggle(i)}
                    aria-sort={sort?.column === i ? (sort.descending ? 'descending' : 'ascending') : undefined}>
                  {c.name}{sort?.column === i ? (sort.descending ? ' ↓' : ' ↑') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, r) => (
              <tr key={r}>
                {table.columns.map((c, i) => {
                  const text = cellText(row[i], c, formats?.[c.name])
                  return <td key={i} className={numeric[i] ? 'num' : undefined} title={text.length > 40 ? text : undefined}>{text}</td>
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {(total > rows.length || table.truncated) && (
        <div className="dt-note">
          {total > rows.length ? `Showing the first ${rows.length.toLocaleString('en-US')} of ${total.toLocaleString('en-US')} rows.` : ''}
          {table.truncated ? ' The result was cut short on the server.' : ''}
        </div>
      )}
    </div>
  )
}

export default memo(DataTable)
