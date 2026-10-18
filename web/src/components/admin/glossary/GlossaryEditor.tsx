// The admin's edit table of a cube's glossary: one row per term (Term, Meaning, In the data, Date to use,
// Status, Agreed by), rows added and removed, saved in one go (PUT /glossary/{cube}).
// Key it by cube and last update so it starts again from the saved rows.
import { useState } from 'react'
import { ActionIcon, Alert, Button, Group, Select, Stack, Table, Text, Textarea, TextInput, Tooltip } from '@mantine/core'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../../api/client'
import ErrorNote from '../ErrorNote'
import { addRow, cleanRows, isChanged, normalizeRow, removeRow, rowProblems, updateCell } from '../glossaryRows'
import { CheckIcon, PlusIcon, TrashIcon, WarnIcon } from '../icons'
import { GLOSSARY_STATUSES, type GlossaryColumn, type GlossaryData, type GlossaryRow } from '../types'

const HEADERS: { column: GlossaryColumn; title: string; help?: string; width?: number }[] = [
  { column: 'Term', title: 'Term', width: 150 },
  { column: 'Meaning', title: 'Meaning', width: 300 },
  { column: 'Measure', title: 'In the data', help: 'Exact measure, column or filter, e.g. [Final Sales]', width: 220 },
  { column: 'Date to use', title: 'Date to use', help: "e.g. 'Create Date'[Create Date]", width: 180 },
  { column: 'Status', title: 'Status', width: 120 },
  { column: 'Agreed by', title: 'Agreed by', help: 'Who confirmed it, e.g. Finance - J. Smith', width: 170 },
]

export default function GlossaryEditor({ cube, rows: saved }: { cube: string; rows: GlossaryRow[] }) {
  const qc = useQueryClient()
  const [rows, setRows] = useState<GlossaryRow[]>(() => saved.map(normalizeRow))
  const [savedNote, setSavedNote] = useState(false)
  const problems = rowProblems(rows)
  const changed = isChanged(saved, rows)
  const save = useMutation({
    mutationFn: () => api.put<GlossaryData>(`/glossary/${encodeURIComponent(cube)}`, { rows: cleanRows(rows) }),
    onSuccess: (data) => {
      setSavedNote(true)
      if (data && Array.isArray(data.rows)) qc.setQueryData(['glossary', cube], data)
      else void qc.invalidateQueries({ queryKey: ['glossary', cube] })
      void qc.invalidateQueries({ queryKey: ['cubes'] })
    },
  })
  const edit = (next: GlossaryRow[]) => {
    setRows(next)
    setSavedNote(false)
  }

  return (
    <Stack gap="sm" data-testid="glossary-editor">
      <Table.ScrollContainer minWidth={1100}>
        <Table withTableBorder verticalSpacing={4} horizontalSpacing={6} data-testid="glossary-edit-table">
          <Table.Thead>
            <Table.Tr>
              {HEADERS.map((h) => (
                <Table.Th key={h.column} w={h.width}>
                  {h.help ? <Tooltip label={h.help}><span style={{ cursor: 'help' }}>{h.title}</span></Tooltip> : h.title}
                </Table.Th>
              ))}
              <Table.Th w={44} />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((r, i) => (
              <Table.Tr key={i} data-testid={`glossary-row-${i}`}>
                {HEADERS.map(({ column, title, help }) => (
                  <Table.Td key={column} style={{ verticalAlign: 'top' }}>
                    {column === 'Status' ? (
                      <Select size="xs" aria-label={`${title}, row ${i + 1}`} data={[...GLOSSARY_STATUSES]}
                              value={r.Status} allowDeselect={false} data-testid={`glossary-cell-${i}-Status`}
                              onChange={(v) => edit(updateCell(rows, i, 'Status', v ?? 'Draft'))} />
                    ) : column === 'Meaning' ? (
                      <Textarea size="xs" autosize minRows={1} maxRows={6} aria-label={`${title}, row ${i + 1}`}
                                value={r.Meaning} data-testid={`glossary-cell-${i}-Meaning`}
                                onChange={(e) => edit(updateCell(rows, i, 'Meaning', e.currentTarget.value))} />
                    ) : (
                      <TextInput size="xs" aria-label={`${title}, row ${i + 1}`} value={r[column]}
                                 placeholder={i === rows.length - 1 && !r[column] ? help?.replace(/^.*e\.g\. /, '') : undefined}
                                 data-testid={`glossary-cell-${i}-${column}`}
                                 ff={column === 'Measure' || column === 'Date to use' ? 'monospace' : undefined}
                                 onChange={(e) => edit(updateCell(rows, i, column, e.currentTarget.value))} />
                    )}
                  </Table.Td>
                ))}
                <Table.Td style={{ verticalAlign: 'top' }}>
                  <Tooltip label="Remove this row">
                    <ActionIcon variant="subtle" color="red" aria-label={`Remove row ${i + 1}`}
                                onClick={() => edit(removeRow(rows, i))} data-testid={`glossary-remove-row-${i}`}>
                      <TrashIcon size={16} />
                    </ActionIcon>
                  </Tooltip>
                </Table.Td>
              </Table.Tr>
            ))}
            {rows.length === 0 && (
              <Table.Tr><Table.Td colSpan={HEADERS.length + 1}><Text size="sm" c="dimmed">No terms yet. Add one.</Text></Table.Td></Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>

      {problems.length > 0 && (
        <Alert color="yellow" icon={<WarnIcon />} data-testid="glossary-problems">
          {problems.map((p) => <Text key={p} size="sm">{p}</Text>)}
        </Alert>
      )}
      <Group gap="sm">
        <Button variant="default" leftSection={<PlusIcon size={16} />} onClick={() => edit(addRow(rows))}
                data-testid="glossary-add-row">
          Add a term
        </Button>
        <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!changed || problems.length > 0}
                data-testid="glossary-save">
          Save glossary
        </Button>
        {changed && !save.isPending && <Text size="sm" c="dimmed">Unsaved changes</Text>}
      </Group>
      <ErrorNote error={save.error} />
      {savedNote && !changed && (
        <Alert color="teal" icon={<CheckIcon />} data-testid="glossary-saved">
          Saved. Claude uses the new definitions from the next question.
        </Alert>
      )}
    </Stack>
  )
}
