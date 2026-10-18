// Editing the glossary table (pure functions, so they are easy to test). Rows are kept as the server
// sends them: Term, Meaning, Measure ("In the data"), Date to use, Status (Draft/Agreed), Agreed by.
import { GLOSSARY_COLUMNS, GLOSSARY_STATUSES, type GlossaryColumn, type GlossaryRow } from './types'

export function newRow(): GlossaryRow {
  return { Term: '', Meaning: '', Measure: '', 'Date to use': '', Status: 'Draft', 'Agreed by': '' }
}

/** Every column present as a string (rows from older files can miss some). */
export function normalizeRow(row: Partial<Record<string, unknown>>): GlossaryRow {
  const out = newRow()
  for (const c of GLOSSARY_COLUMNS) out[c] = row[c] == null ? (c === 'Status' ? 'Draft' : '') : String(row[c])
  if (!(GLOSSARY_STATUSES as readonly string[]).includes(out.Status)) out.Status = 'Draft'
  return out
}

export const addRow = (rows: GlossaryRow[]): GlossaryRow[] => [...rows, newRow()]

export const removeRow = (rows: GlossaryRow[], index: number): GlossaryRow[] => rows.filter((_, i) => i !== index)

export function updateCell(rows: GlossaryRow[], index: number, column: GlossaryColumn, value: string): GlossaryRow[] {
  return rows.map((r, i) => (i === index ? { ...r, [column]: value } : r))
}

const isBlank = (r: GlossaryRow) => GLOSSARY_COLUMNS.every((c) => c === 'Status' || !r[c].trim())

/** What gets saved: values trimmed, empty rows left out, unknown statuses as Draft (as glossary.save). */
export function cleanRows(rows: GlossaryRow[]): GlossaryRow[] {
  return rows.filter((r) => !isBlank(r)).map((r) => normalizeRow(
    Object.fromEntries(GLOSSARY_COLUMNS.map((c) => [c, r[c].trim()]))))
}

/** Reasons the table can't be saved yet, in plain words (empty when it can). Row numbers count from 1
 * as on screen. */
export function rowProblems(rows: GlossaryRow[]): string[] {
  const problems: string[] = []
  const seen = new Map<string, number>()
  rows.forEach((r, i) => {
    if (isBlank(r)) return
    const term = r.Term.trim()
    if (!term) {
      problems.push(`Row ${i + 1} has no term. Add one or remove the row.`)
      return
    }
    const key = term.toLowerCase()
    if (seen.has(key)) problems.push(`"${term}" is in the table twice (rows ${seen.get(key)! + 1} and ${i + 1}).`)
    else seen.set(key, i)
  })
  return problems
}

/** True when the table differs from what was loaded (ignoring blank rows and spaces). */
export function isChanged(original: GlossaryRow[], edited: GlossaryRow[]): boolean {
  return JSON.stringify(cleanRows(original.map(normalizeRow))) !== JSON.stringify(cleanRows(edited))
}

export const isAgreed = (r: Partial<GlossaryRow>) => r.Status === 'Agreed'
