// A server job as a status box (like st.status): a headline, every progress line as it arrives, and the
// outcome. The caller follows the job with useJobProgress and passes its progress here.
// `words` are the three headlines (running, done, failed).
import { useEffect, useRef } from 'react'
import { Alert, Button, Group, Loader, Paper, ScrollArea, Stack, Text } from '@mantine/core'
import { isActive, jobHeadline, type JobProgress } from './jobProgress'
import { CheckIcon, ErrorIcon } from './icons'

export type JobLogProps = {
  progress: JobProgress
  words: { running: string; done: string; failed: string }
  onHide?: () => void
  testId?: string
}

export default function JobLog({ progress, words, onHide, testId }: JobLogProps) {
  const viewport = useRef<HTMLDivElement>(null)
  useEffect(() => {   // keep the newest line in view
    viewport.current?.scrollTo({ top: viewport.current.scrollHeight })
  }, [progress.lines.length])

  if (progress.phase === 'idle') return null
  const running = isActive(progress)
  const colour = progress.phase === 'done' ? 'teal' : progress.phase === 'failed' ? 'red' : undefined
  return (
    <Paper withBorder p="md" radius="md" data-testid={testId ?? 'job-log'} data-phase={progress.phase}>
      <Stack gap="xs">
        <Group justify="space-between" wrap="nowrap">
          <Group gap={8} wrap="nowrap">
            {running ? <Loader size={16} /> : progress.phase === 'done'
              ? <Text c="teal" span lh={0}><CheckIcon /></Text>
              : <Text c="red" span lh={0}><ErrorIcon /></Text>}
            <Text fw={600} c={colour} data-testid="job-headline">{jobHeadline(progress, words)}</Text>
          </Group>
          {!running && onHide && <Button variant="subtle" size="xs" onClick={onHide}>Hide</Button>}
        </Group>
        {progress.lines.length > 0 && (
          <ScrollArea.Autosize mah={240} viewportRef={viewport} type="auto">
            <Stack gap={2} data-testid="job-lines">
              {progress.lines.map((line, i) => <Text key={i} size="sm" ff="monospace">{line}</Text>)}
            </Stack>
          </ScrollArea.Autosize>
        )}
        {progress.phase === 'failed' && progress.error && (
          <Alert color="red" p="xs"><Text size="sm">{progress.error}</Text></Alert>
        )}
      </Stack>
    </Paper>
  )
}
