// The "Working on it..." panel of an answer (Streamlit's status box): the progress lines as they arrive,
// collapsible; it opens by itself when the numbers arrive to show them before the chart is drawn.
import { memo, useState } from 'react'
import { Box, Collapse, Group, Loader, Paper, Stack, Text, UnstyledButton } from '@mantine/core'
import DataTable from '../DataTable'
import { AlertIcon, CheckIcon, ChevronIcon, InfoIcon } from './icons'
import type { TurnView } from './types'

function label(turn: TurnView): string {
  switch (turn.status) {
    case 'streaming': return turn.table ? 'Got the data - drawing the chart...' : 'Working on it...'
    case 'stopped': return 'Stopped'
    case 'error': return 'Something went wrong'
    default: return turn.clarify ? 'I need a bit more detail' : 'Done'
  }
}

function StatusIcon({ turn }: { turn: TurnView }) {
  if (turn.status === 'streaming') return <Loader size={14} />
  if (turn.status === 'error') return <AlertIcon color="var(--mantine-color-red-6)" />
  if (turn.status === 'stopped' || turn.clarify) return <InfoIcon color="var(--mantine-color-dimmed)" />
  return <CheckIcon color="var(--mantine-color-green-6)" />
}

function ProgressPanel({ turn }: { turn: TurnView }) {
  const [userOpen, setUserOpen] = useState<boolean | null>(null) // null: open by itself while it shows the data
  const streaming = turn.status === 'streaming'
  const open = userOpen ?? (streaming && !!turn.table && !turn.chart) // closes again once the chart is drawn
  const latest = turn.steps[turn.steps.length - 1]
  return (
    <Paper withBorder radius="md" px="sm" py={6} data-testid="chat-progress" data-status={turn.status}>
      <UnstyledButton onClick={() => setUserOpen(!open)} w="100%" aria-expanded={open}
                      data-testid="chat-progress-toggle">
        <Group gap="xs" wrap="nowrap">
          <StatusIcon turn={turn} />
          <Text size="sm" fw={500} data-testid="chat-progress-label">{label(turn)}</Text>
          {streaming && !open && latest && (
            <Text size="xs" c="dimmed" truncate style={{ flex: 1, minWidth: 0 }}>{latest}</Text>
          )}
          <Box ml="auto" c="dimmed" style={{ display: 'flex' }}><ChevronIcon open={open} /></Box>
        </Group>
      </UnstyledButton>
      <Collapse expanded={open} keepMounted={false}>
        <Stack gap={4} pt="xs" pb={4}>
          {turn.steps.map((step, i) => (
            <Text key={i} size="sm" c="dimmed" data-testid="chat-progress-step">{step}</Text>
          ))}
          {streaming && turn.table && (
            <DataTable table={turn.table} maxHeight={300} testId="chat-table-preview" />
          )}
        </Stack>
      </Collapse>
    </Paper>
  )
}

export default memo(ProgressPanel)
