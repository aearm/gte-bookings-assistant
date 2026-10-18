// Time per stage of answering a question (planning, checks, the query, the chart...), slowest first.
import { Progress, Table, Text } from '@mantine/core'
import { percent, secondsText } from '../format'
import type { StageTime } from '../usageSummary'

export default function StageTable({ stages }: { stages: StageTime[] }) {
  if (!stages.length) return <Text size="sm" c="dimmed">No stage times measured in this period.</Text>
  return (
    <Table.ScrollContainer minWidth={560}>
      <Table striped withTableBorder verticalSpacing="xs" data-testid="usage-stages">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Stage</Table.Th>
            <Table.Th ta="right">Questions</Table.Th>
            <Table.Th ta="right">Average</Table.Th>
            <Table.Th ta="right">Longest</Table.Th>
            <Table.Th w={200}>Share of the question's time</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {stages.map((s) => (
            <Table.Tr key={s.stage} data-testid={`usage-stage-${s.stage}`}>
              <Table.Td>{s.stage.replace(/_/g, ' ')}</Table.Td>
              <Table.Td ta="right">{s.questions.toLocaleString('en-GB')}</Table.Td>
              <Table.Td ta="right">{secondsText(s.average)}</Table.Td>
              <Table.Td ta="right">{secondsText(s.longest)}</Table.Td>
              <Table.Td>
                <Progress value={Math.round(s.share * 100)} size="sm" aria-label={`${s.stage}: ${percent(s.share)}`} />
                <Text size="xs" c="dimmed">{percent(s.share)}</Text>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}
