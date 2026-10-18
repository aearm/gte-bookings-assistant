// One question and its answer: progress, how Claude understood it, a clarifying question, or the chart,
// the written answer, notes, the data and the actions (views/chat.py show_turn). Memoized: while one
// answer streams, the others don't re-render.
import { memo, useState } from 'react'
import { Alert, Box, Button, Collapse, Group, LoadingOverlay, Paper, Stack, Text, Tooltip } from '@mantine/core'
import EChart from '../../charts/EChart'
import DataTable from '../DataTable'
import ClarifyBlock from './ClarifyBlock'
import ErrorBlock from './ErrorBlock'
import Markdown from './Markdown'
import ProgressPanel from './ProgressPanel'
import {
  ChartAddIcon, ChevronIcon, CodeIcon, CompassIcon, DownloadIcon, InfoIcon, JoinIcon, PaletteIcon, RetryIcon,
  TableIcon, VerifiedIcon,
} from './icons'
import type { TurnView } from './types'

export type TurnAction = 'add' | 'chart' | 'query'

type Props = {
  turn: TurnView
  conversationId: string | null
  isAdmin: boolean
  dark: boolean
  /** The last turn: the only one that can be asked again or answered. */
  isLast: boolean
  /** An answer is streaming in this conversation. */
  busy: boolean
  cubeLabels: Record<string, string>
  onAction: (action: TurnAction, key: string) => void
  onAnswer: (answer: string) => void
  onRetry: (key: string) => void
  onVerify: (key: string) => void
}

const rowsText = (n: number) => `${n.toLocaleString()} row${n === 1 ? '' : 's'}`

function TurnCard({ turn, conversationId, isAdmin, dark, isLast, busy, cubeLabels, onAction, onAnswer, onRetry, onVerify }: Props) {
  const [showData, setShowData] = useState(false)
  const { chart, table } = turn
  const done = turn.status === 'done'
  const hasRows = !!table && table.rows.length > 0
  const failed = turn.status === 'error' || turn.status === 'stopped'
  const summary = chart?.summary || turn.answerText || ''
  const drawn = !!chart?.option
  const canAct = done && !!turn.id && hasRows && !turn.clarify
  const csvHref = conversationId && turn.id ? `/api/conversations/${conversationId}/turns/${turn.id}/csv` : undefined

  return (
    <Stack gap="sm" data-testid="chat-turn" data-turn-id={turn.id || undefined} data-status={turn.status}>
      <Group justify="flex-end">
        <Paper px="md" py={8} radius="lg" bg="var(--mantine-color-default-hover)" maw="85%" data-testid="chat-question">
          <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{turn.question}</Text>
        </Paper>
      </Group>

      <Stack gap="sm">
        {(turn.status === 'streaming' || turn.steps.length > 0) && <ProgressPanel turn={turn} />}

        {turn.status === 'error' && <ErrorBlock message={turn.error || 'Something went wrong.'} details={turn.details} />}
        {turn.status === 'stopped' && (
          <Text size="sm" c="dimmed" data-testid="chat-stopped">Stopped before the answer was ready.</Text>
        )}
        {failed && isLast && (
          <Button variant="subtle" size="xs" leftSection={<RetryIcon />} disabled={busy}
                  onClick={() => onRetry(turn.key)} style={{ alignSelf: 'flex-start' }} data-testid="chat-retry">
            Ask again
          </Button>
        )}

        {!failed && turn.understanding && (
          <Alert variant="light" color="blue" icon={<CompassIcon />} p="xs" data-testid="chat-understanding">
            <Text size="sm"><strong>I understood your question as:</strong> {turn.understanding}</Text>
          </Alert>
        )}

        {!failed && turn.clarify && (
          <ClarifyBlock question={turn.clarify.question} options={turn.clarify.options}
                        answered={!!turn.answered || !isLast} busy={busy} onAnswer={onAnswer} />
        )}

        {!failed && !turn.clarify && (chart || summary) && (
          <>
            <Markdown text={summary} testId="chat-summary" />
            {turn.cubes.length > 1 && (
              <Group gap={6} c="dimmed" data-testid="chat-cubes">
                <JoinIcon size={14} />
                <Text size="xs">Combined from {turn.cubes.map(c => cubeLabels[c] || c).join(' + ')}</Text>
              </Group>
            )}
            {chart?.note && <Note text={chart.note} testId="chat-chart-note" />}
            {hasRows && turn.notes.map((note, i) => <Note key={i} text={note} testId="chat-note" />)}
          </>
        )}

        {!failed && !turn.clarify && (drawn || (table && (done || chart))) && (
          <Box pos="relative" data-testid="chat-answer">
            <LoadingOverlay visible={!!turn.redrawing} zIndex={5} overlayProps={{ blur: 1 }}
                            loaderProps={{ children: <Text size="sm">Claude is drawing the chart you described...</Text> }} />
            {drawn
              ? <EChart option={chart!.option!} dark={dark} testId="chat-chart"
                        height={['map', 'custom'].includes(chart!.kind) ? 440 : undefined} />
              : <DataTable table={table!} maxHeight={420} testId="chat-table" />}
          </Box>
        )}
        {turn.chartError && (
          <Text size="sm" c="red" data-testid="chat-chart-error">{turn.chartError}</Text>
        )}

        {canAct && (
          <Group gap="xs" data-testid="chat-actions">
            <Button variant="default" size="xs" leftSection={<PaletteIcon />} onClick={() => onAction('chart', turn.key)}
                    disabled={turn.redrawing} data-testid="chat-action-change-chart">
              Change chart
            </Button>
            <Button variant="default" size="xs" leftSection={<ChartAddIcon />} onClick={() => onAction('add', turn.key)}
                    data-testid="chat-action-add">
              Add to dashboard
            </Button>
            {turn.query && (
              <Button variant="subtle" size="xs" leftSection={<CodeIcon />} onClick={() => onAction('query', turn.key)}
                      data-testid="chat-action-query">
                Show the query
              </Button>
            )}
            {csvHref && (
              <Button component="a" href={csvHref} download="result.csv" variant="subtle" size="xs"
                      leftSection={<DownloadIcon />} data-testid="chat-action-csv">
                Download CSV
              </Button>
            )}
            {isAdmin && turn.answer_id != null && !turn.verified && (
              <Tooltip label="Claude uses answers marked correct as examples for similar questions" withArrow>
                <Button variant="subtle" size="xs" leftSection={<VerifiedIcon />} onClick={() => onVerify(turn.key)}
                        data-testid="chat-action-verify">
                  Mark as correct
                </Button>
              </Tooltip>
            )}
          </Group>
        )}
        {turn.verified && (
          <Group gap={6} c="dimmed" data-testid="chat-verified">
            <VerifiedIcon size={14} />
            <Text size="xs">Marked as correct: Claude follows it for similar questions.</Text>
          </Group>
        )}

        {done && !turn.clarify && table && drawn && (
          <div>
            <Button variant="subtle" size="xs" color="gray" onClick={() => setShowData(s => !s)}
                    leftSection={<TableIcon />} rightSection={<ChevronIcon open={showData} size={14} />}
                    aria-expanded={showData} data-testid="chat-data-toggle">
              Data ({rowsText(table.row_count)})
            </Button>
            <Collapse expanded={showData} keepMounted={false}>
              <Box pt="xs">
                <DataTable table={table} maxHeight={360} testId="chat-table" />
                {table.truncated && (
                  <Text size="xs" c="dimmed" mt={4}>
                    Showing the first {rowsText(table.rows.length)} of {rowsText(table.row_count)}. Download CSV for all of them.
                  </Text>
                )}
              </Box>
            </Collapse>
          </div>
        )}
      </Stack>
    </Stack>
  )
}

function Note({ text, testId }: { text: string; testId: string }) {
  return (
    <Group gap={6} c="dimmed" wrap="nowrap" align="flex-start" data-testid={testId}>
      <InfoIcon size={14} style={{ marginTop: 2, flexShrink: 0 }} />
      <Text size="xs">{text}</Text>
    </Group>
  )
}

export default memo(TurnCard)
