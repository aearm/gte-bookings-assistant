// The latest questions (and, if asked, every other Claude activity): when, what, how long, what it cost.
import { Badge, Table, Text } from '@mantine/core'
import { money, percent, whenText } from '../format'
import type { UsageEntry } from '../types'
import { kindLabel } from '../usageSummary'

export default function RecentTable({ entries }: { entries: UsageEntry[] }) {
  if (!entries.length) return <Text size="sm" c="dimmed">Nothing measured in this period.</Text>
  return (
    <Table.ScrollContainer minWidth={900} maxHeight={560}>
      <Table striped stickyHeader withTableBorder verticalSpacing={6} data-testid="usage-recent">
        <Table.Thead>
          <Table.Tr>
            <Table.Th w={110}>When</Table.Th>
            <Table.Th w={140}>Kind</Table.Th>
            <Table.Th>Question</Table.Th>
            <Table.Th ta="right" w={80}>Seconds</Table.Th>
            <Table.Th ta="right" w={80}>Cost ($)</Table.Th>
            <Table.Th ta="right" w={90}>Claude calls</Table.Th>
            <Table.Th ta="right" w={90}>From cache</Table.Th>
            <Table.Th w={160}>Answer</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {entries.map((e, i) => (
            <Table.Tr key={`${e.time}-${i}`} data-testid="usage-recent-row">
              <Table.Td><Text size="sm" style={{ whiteSpace: 'nowrap' }}>{whenText(e.time)}</Text></Table.Td>
              <Table.Td><Text size="sm">{kindLabel(e.kind)}</Text></Table.Td>
              <Table.Td>
                <Text size="sm" lineClamp={2} title={e.label}>{e.label}</Text>
              </Table.Td>
              <Table.Td ta="right">{(e.seconds ?? 0).toFixed(1)}</Table.Td>
              <Table.Td ta="right">{money(e.cost, 3).slice(1)}</Table.Td>
              <Table.Td ta="right">{e.claude_calls ?? 0}</Table.Td>
              <Table.Td ta="right">{e.claude_calls ? percent(e.cache_hit ?? 0) : '–'}</Table.Td>
              <Table.Td>
                {e.error ? <Text size="xs" c="red" lineClamp={2} title={e.error}>{e.error.slice(0, 80)}</Text>
                  : e.memory ? <Badge size="sm" variant="light">From memory</Badge>
                  : <Text size="sm">{e.outcome ?? ''}</Text>}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}
