// Usage (admins only): what questions cost and how long they take, from data/usage.jsonl (written by
// usage.py for every question, chart, setup step and data layer build): the latest questions, and the cost
// report of every Claude activity.
import { Box, Center, Group, Loader, SegmentedControl, Stack, Text } from '@mantine/core'
import { useSearchParams } from 'react-router-dom'
import AdminOnly from '../../components/admin/AdminOnly'
import ErrorNote from '../../components/admin/ErrorNote'
import PageHeader, { Section } from '../../components/admin/PageHeader'
import { useUsage } from '../../components/admin/queries'
import CostReportPanel from '../../components/admin/usage/CostReportPanel'
import RecentTable from '../../components/admin/usage/RecentTable'
import StageTable from '../../components/admin/usage/StageTable'
import UsageWindows from '../../components/admin/usage/UsageWindows'
import { inLastDays, newestFirst, RECENT_LIMIT, stageTimes } from '../../components/admin/usageSummary'

const DAYS = ['7', '30', '90']

/** "Today" as the server counts it (the last day of its daily report), else the browser's. */
function serverToday(daily: { Day: string }[] | undefined): Date {
  const last = daily?.[daily.length - 1]?.Day
  const m = last && /^(\d{4})-(\d{2})-(\d{2})/.exec(last)
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date()
}

function UsageContent() {
  const [params, setParams] = useSearchParams()
  const days = DAYS.includes(params.get('days') ?? '') ? Number(params.get('days')) : 30
  const usage = useUsage(days)

  const picker = (
    <Group gap="sm">
      <Text size="sm" c="dimmed">Period</Text>
      <SegmentedControl size="xs" value={String(days)} data-testid="usage-days"
                        data={DAYS.map((d) => ({ value: d, label: `${d} days` }))}
                        onChange={(v) => setParams((p) => { p.set('days', v); return p }, { replace: true })} />
    </Group>
  )
  if (usage.isLoading) return <Stack>{picker}<Center py="xl"><Loader size="sm" /></Center></Stack>
  if (usage.error || !usage.data) return <Stack>{picker}<ErrorNote error={usage.error ?? 'Usage could not be read.'} /></Stack>

  const { report, recent = [] } = usage.data
  const today = serverToday(report?.daily)
  const period = inLastDays(recent, days, today)
  const questions = period.filter((e) => e.kind === 'question')
  const listed = newestFirst(questions, RECENT_LIMIT)

  return (
    <Stack gap={0}>
      {picker}
      {questions.length === 0 && recent.length === 0 ? (
        <Text size="sm" c="dimmed" mt="md" data-testid="usage-empty">No questions measured yet. Ask something in Chat.</Text>
      ) : (
        <>
          <Section title="Questions and cost">
            <UsageWindows entries={recent} days={days} today={today} daily={report?.daily} />
          </Section>
          <Section title="Time per stage" caption={`Where the time of a question goes, over the last ${days} days.`}>
            <StageTable stages={stageTimes(period)} />
          </Section>
          <Section title="Recent questions" testId="usage-recent-section"
                   caption={recent.length >= RECENT_LIMIT ? `The latest ${RECENT_LIMIT} questions within the last ${days} days, newest first.`
                     : `The last ${days} days, newest first.`}>
            <RecentTable entries={listed} />
          </Section>
        </>
      )}
      {report && (
        <Section title="Claude cost">
          <CostReportPanel report={report} />
        </Section>
      )}
    </Stack>
  )
}

export default function UsagePage() {
  return (
    <Box data-testid="UsagePage" maw={1200}>
      <PageHeader title="Usage" caption="How long questions take and what they cost in Claude, per question and per stage." />
      <AdminOnly what="The Usage page"><UsageContent /></AdminOnly>
    </Box>
  )
}
