import { describe, expect, it } from 'vitest'
import { addRow, cleanRows, isChanged, newRow, normalizeRow, removeRow, rowProblems, updateCell } from '../glossaryRows'
import type { GlossaryRow } from '../types'

const row = (over: Partial<GlossaryRow>): GlossaryRow => ({ ...newRow(), ...over })
const saved: GlossaryRow[] = [
  row({ Term: 'Bookings', Meaning: 'Confirmed bookings', Measure: '[Booking Count]', Status: 'Agreed', 'Agreed by': 'Admin setup' }),
  row({ Term: 'Booking date', Meaning: 'The day the booking was made', 'Date to use': "'Create Date'[Create Date]" }),
]

describe('glossary row editing', () => {
  it('adds an empty draft row at the end', () => {
    const rows = addRow(saved)
    expect(rows).toHaveLength(3)
    expect(rows[2]).toEqual({ Term: '', Meaning: '', Measure: '', 'Date to use': '', Status: 'Draft', 'Agreed by': '' })
    expect(saved).toHaveLength(2)   // the original is not changed
  })

  it('removes a row by position', () => {
    expect(removeRow(saved, 0).map((r) => r.Term)).toEqual(['Booking date'])
  })

  it('changes one cell and leaves the rest', () => {
    const rows = updateCell(saved, 1, 'Status', 'Agreed')
    expect(rows[1].Status).toBe('Agreed')
    expect(rows[0]).toBe(saved[0])
    expect(saved[1].Status).toBe('Draft')
  })

  it('normalizes rows from older files (missing columns, unknown status)', () => {
    expect(normalizeRow({ Term: 'Sales', Status: 'Maybe' })).toEqual(row({ Term: 'Sales', Status: 'Draft' }))
    expect(normalizeRow({ Term: 'Sales' }).Status).toBe('Draft')
  })

  it('saves trimmed values and leaves blank rows out', () => {
    const rows = [...saved, newRow(), row({ Term: '  Sales ', Meaning: ' Final sales  ' })]
    const clean = cleanRows(rows)
    expect(clean).toHaveLength(3)
    expect(clean[2]).toEqual(row({ Term: 'Sales', Meaning: 'Final sales' }))
  })

  it('names rows that have content but no term, and repeated terms', () => {
    expect(rowProblems(saved)).toEqual([])
    expect(rowProblems([...saved, newRow()])).toEqual([])   // a blank row is just left out
    expect(rowProblems([...saved, row({ Meaning: 'something' })])).toEqual(['Row 3 has no term. Add one or remove the row.'])
    expect(rowProblems([...saved, row({ Term: 'bookings ' })])).toEqual(['"bookings" is in the table twice (rows 1 and 3).'])
  })

  it('knows when the table was changed', () => {
    expect(isChanged(saved, saved.map(normalizeRow))).toBe(false)
    expect(isChanged(saved, addRow(saved))).toBe(false)              // an empty new row is no change yet
    expect(isChanged(saved, updateCell(saved, 0, 'Meaning', 'x'))).toBe(true)
    expect(isChanged(saved, removeRow(saved, 1))).toBe(true)
    expect(isChanged(saved, updateCell(saved, 0, 'Term', 'Bookings  '))).toBe(false)   // spaces only
  })
})
