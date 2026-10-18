// "Claude cost" (usage.cost_report): this month and everything measured, cost per day, by activity and by
// model, with the note that these are estimates from list prices.
import { Anchor, Group, Paper, SimpleGrid, Stack, Table, Text } from '@mantine/core'
import EChart from '../../../charts/EChart'
import { money, whenText } from '../format'
import type { CostReport } from '../types'

function Total({ label, value, testId }: { label: string; value: number; testId?: string }) {
  return (
    <Paper withBorder p="sm" radius="md">
      <Text size="xs" c="dimmed">{label}</Text>
      <Text size="lg" fw={700} data-testid={testId}>{money(value)}</Text>
    </Paper>
  )
}

function dailyOption(daily: CostReport['daily']) {
  return {
    grid: { left: 48, right: 8, top: 12, bottom: 28 },
    tooltip: { trigger: 'axis', valueFormatter: (v: number) => money(v) },
    xAxis: { type: 'category', data: daily.map((d) => whenText(d.Day)), axisTick: { alignWithLabel: true } },
    yAxis: { type: 'value', axisLabel: { formatter: '${value}' }, min: 0 },
    series: [{ type: 'bar', name: 'Cost', data: daily.map((d) => d['Cost ($)']), barMaxWidth: 28, itemStyle: { color: '#0a84ff' } }],
  }
}

export default function CostReportPanel({ report }: { report: CostReport }) {
  if (!report.since) {
    return (
      <Text size="sm" c="dimmed" data-testid="usage-cost-empty">
        Nothing measured yet. The cost of each question, chart and setup step appears here.
      </Text>
    )
  }
  const since = whenText(report.since, true)
  const daily = (report.daily ?? []).filter((d) => d.Day >= report.since!)   // from the first measured day
  return (
    <Stack gap="md" data-testid="usage-cost">
      <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="sm">
        <Total label="Today" value={report.today} />
        <Total label="Last 7 days" value={report.week} />
        <Total label="This month" value={report.month} testId="usage-cost-month" />
        <Total label={`Since ${since}`} value={report.total} testId="usage-cost-total" />
      </SimpleGrid>
      {daily.length > 0 && <EChart option={dailyOption(daily)} height={190} testId="usage-daily-chart" />}

      {report.activities?.length > 0 && (
        <Table.ScrollContainer minWidth={560}>
          <Table striped withTableBorder verticalSpacing="xs" data-testid="usage-activities">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Activity</Table.Th>
                <Table.Th ta="right">Times</Table.Th>
                <Table.Th ta="right">From memory</Table.Th>
                <Table.Th ta="right">This month ($)</Table.Th>
                <Table.Th ta="right">Total ($)</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {report.activities.map((a) => (
                <Table.Tr key={a.Activity}>
                  <Table.Td>{a.Activity}</Table.Td>
                  <Table.Td ta="right">{a.Times.toLocaleString('en-GB')}</Table.Td>
                  <Table.Td ta="right">{a['From memory'].toLocaleString('en-GB')}</Table.Td>
                  <Table.Td ta="right">{money(a['This month ($)'])}</Table.Td>
                  <Table.Td ta="right">{money(a['Total ($)'])}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      {report.models?.length > 0 && (
        <Stack gap={4}>
          <Text size="sm" fw={600}>By model</Text>
          <Table.ScrollContainer minWidth={560}>
            <Table striped withTableBorder verticalSpacing="xs" data-testid="usage-models">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Model</Table.Th>
                  <Table.Th ta="right">Calls</Table.Th>
                  <Table.Th ta="right">Tokens read</Table.Th>
                  <Table.Th ta="right">Tokens written</Table.Th>
                  <Table.Th ta="right">Total ($)</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {report.models.map((m) => (
                  <Table.Tr key={m.Model}>
                    <Table.Td><Text size="sm" ff="monospace">{m.Model}</Text></Table.Td>
                    <Table.Td ta="right">{m.Calls.toLocaleString('en-GB')}</Table.Td>
                    <Table.Td ta="right">{m['Tokens read'].toLocaleString('en-GB')}</Table.Td>
                    <Table.Td ta="right">{m['Tokens written'].toLocaleString('en-GB')}</Table.Td>
                    <Table.Td ta="right">{money(m['Total ($)'])}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Stack>
      )}

      <Group gap={4}>
        <Text size="xs" c="dimmed">
          Estimated from Claude's list prices for every call this app has made since {since}, when measuring started.
          Questions answered from memory (asked again the same day) cost nothing. The exact bill, including anything
          before that date, is at{' '}
          <Anchor href="https://platform.claude.com/settings/billing" target="_blank" rel="noreferrer" size="xs">
            platform.claude.com
          </Anchor>.
        </Text>
      </Group>
    </Stack>
  )
}
