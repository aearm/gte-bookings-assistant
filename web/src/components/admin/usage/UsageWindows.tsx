// Today, the last 7 days and the period picked: questions, what Claude cost, the average per question,
// how much of the prompts came from Claude's cache, the median time and repeats answered from memory.
import { Group, Paper, SimpleGrid, Stack, Text } from '@mantine/core'
import { money, percent, secondsText } from '../format'
import type { CostReport, UsageEntry } from '../types'
import { summarize, summaryWindows, windowLabel } from '../usageSummary'

function Figure({ label, value, testId }: { label: string; value: string; testId?: string }) {
  return (
    <Group justify="space-between" gap="xs" wrap="nowrap">
      <Text size="sm" c="dimmed">{label}</Text>
      <Text size="sm" fw={600} data-testid={testId}>{value}</Text>
    </Group>
  )
}

export default function UsageWindows({ entries, days, today, daily }: {
  entries: UsageEntry[]; days: number; today: Date; daily?: CostReport['daily']
}) {
  const windows = summaryWindows(days).map((d) => summarize(entries, d, today, daily))
  const partial = windows.some((w) => w.partial)
  return (
    <Stack gap="xs">
      <SimpleGrid cols={{ base: 1, sm: windows.length }} spacing="md" data-testid="usage-summary">
        {windows.map((w) => (
          <Paper key={w.days} withBorder p="md" radius="md" data-testid={`usage-window-${w.days}`}>
            <Stack gap={6}>
              <Text fw={600}>{windowLabel(w.days)}</Text>
              <Figure label="Questions" value={w.questions.toLocaleString('en-GB')} testId={`usage-questions-${w.days}`} />
              <Figure label="Claude cost" value={money(w.cost)} testId={`usage-cost-${w.days}`} />
              <Figure label="Average cost per question" value={w.averageCost == null ? '–' : money(w.averageCost, 3)} />
              <Figure label="Cache use" value={percent(w.cacheUse)} />
              <Figure label="Median time per question" value={secondsText(w.medianSeconds)} />
              <Figure label="Answered from memory" value={w.questions ? `${w.fromMemory} of ${w.questions}` : '–'} />
            </Stack>
          </Paper>
        ))}
      </SimpleGrid>
      {partial && (
        <Text size="xs" c="dimmed">
          Questions, averages and cache use are from the latest 300 questions; Claude cost covers everything.
        </Text>
      )}
    </Stack>
  )
}
