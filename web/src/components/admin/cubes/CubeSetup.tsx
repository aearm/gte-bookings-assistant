// "Business words of a cube": the guided setup of one cube (cube_setup.py). 1 read the structure and
// values (a job; the data layer build reads them too), 2 Claude drafts the map (a job), 3 the admin answers
// the few unclear questions or skips them, 4 confirms what Claude understood. Then the cube is ready.
import { useState, type ReactNode } from 'react'
import { Alert, Anchor, Button, Checkbox, Group, List, Paper, Radio, Stack, Text, TextInput, Title } from '@mantine/core'
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../../../api/client'
import type { Info } from '../../../api/types'
import ErrorNote from '../ErrorNote'
import JobLog from '../JobLog'
import { openProposals, openQuestions, setupProgress, SOMETHING_ELSE } from '../cubeHelpers'
import { whenText } from '../format'
import { CheckIcon, SparkIcon, SyncIcon } from '../icons'
import { isActive } from '../jobProgress'
import { useAdminJobs } from '../jobStore'
import { useCubeSetup } from '../queries'
import { useJobProgress } from '../useJobProgress'
import type { CubeInfo, OpenProposal, OpenQuestion, SetupState } from '../types'

const enc = encodeURIComponent

/** A setup call's answer is the new state: show it at once (and refresh what depends on it). */
function applyState(qc: QueryClient, cube: string, result: unknown) {
  const state = result as SetupState | null
  if (state && typeof state === 'object' && (Array.isArray(state.questions) || Array.isArray(state.items))) {
    qc.setQueryData(['cube-setup', cube], state)
  } else {
    void qc.invalidateQueries({ queryKey: ['cube-setup', cube] })
  }
  void qc.invalidateQueries({ queryKey: ['cubes'] })            // the setup label in the status table
  void qc.invalidateQueries({ queryKey: ['glossary', cube] })   // answers become glossary terms
}

function StepPanel({ title, children, testId }: { title: string; children: ReactNode; testId?: string }) {
  return (
    <Paper withBorder p="md" radius="md" data-testid={testId}>
      <Stack gap="xs">
        <Text fw={600}>{title}</Text>
        {children}
      </Stack>
    </Paper>
  )
}

const Done = ({ children }: { children: ReactNode }) => (
  <Group gap={6} wrap="nowrap" align="flex-start">
    <Text c="teal" span lh={0} mt={1}><CheckIcon size={16} /></Text>
    <Text size="sm" c="dimmed">{children}</Text>
  </Group>
)

/** Follows one of this cube's jobs (read, draft): started here, kept while moving between pages. */
function useCubeJob(purpose: string, onFinish: () => void) {
  const id = useAdminJobs((s) => s.jobs[purpose]) ?? null
  const setJob = useAdminJobs((s) => s.setJob)
  const clearJob = useAdminJobs((s) => s.clearJob)
  const progress = useJobProgress(id, onFinish)
  return { id, progress, start: (job: string) => setJob(purpose, job), hide: () => clearJob(purpose) }
}

// ---------------------------------------------------------------- one question --

function SetupQuestion({ cube, item }: { cube: string; item: OpenQuestion }) {
  const qc = useQueryClient()
  const { index } = item
  const [choice, setChoice] = useState<string | null>(null)
  const [custom, setCustom] = useState('')
  const labels = [...(item.options ?? []).map((o) => o.label), SOMETHING_ELSE]
  const answer = useMutation({
    mutationFn: () => api.post<SetupState>(`/cubes/${enc(cube)}/setup/answer`, choice === SOMETHING_ELSE
      ? { index, custom: custom.trim() } : { index, option: labels.indexOf(choice!) }),
    onSuccess: (state) => applyState(qc, cube, state),
  })
  const skip = useMutation({
    mutationFn: () => api.post<SetupState>(`/cubes/${enc(cube)}/setup/skip`, { index }),
    onSuccess: (state) => applyState(qc, cube, state),
  })
  const busy = answer.isPending || skip.isPending
  return (
    <Paper withBorder p="md" radius="md" data-testid={`setup-question-${index}`}>
      <Stack gap="sm">
        <Title order={5}>{item.question}</Title>
        <Radio.Group value={choice} onChange={setChoice} aria-label={item.term}>
          <Stack gap={6}>
            {labels.map((l, i) => <Radio key={l} value={l} label={l} data-testid={`setup-option-${index}-${i}`} />)}
          </Stack>
        </Radio.Group>
        {choice === SOMETHING_ELSE && (
          <TextInput label="In your words" value={custom} onChange={(e) => setCustom(e.currentTarget.value)}
                     data-testid={`setup-custom-${index}`} />
        )}
        <Group gap="sm">
          <Button onClick={() => answer.mutate()} loading={answer.isPending} data-testid={`setup-answer-${index}`}
                  disabled={busy || choice === null || (choice === SOMETHING_ELSE && !custom.trim())}>
            Save
          </Button>
          <Button variant="default" onClick={() => skip.mutate()} loading={skip.isPending} disabled={busy}
                  data-testid={`setup-skip-${index}`}>
            Not sure
          </Button>
        </Group>
        <ErrorNote error={answer.error ?? skip.error} />
      </Stack>
    </Paper>
  )
}

// ---------------------------------------------------------------- what Claude understood --

function SetupProposals({ cube, step, items }: { cube: string; step: number; items: OpenProposal[] }) {
  const qc = useQueryClient()
  const [unticked, setUnticked] = useState<Set<number>>(new Set())
  const confirm = useMutation({
    mutationFn: () => api.post<SetupState>(`/cubes/${enc(cube)}/setup/confirm`, {
      indexes: items.map((p) => p.index).filter((i) => !unticked.has(i)),
      rejected: items.map((p) => p.index).filter((i) => unticked.has(i)),
    }),
    onSuccess: (state) => applyState(qc, cube, state),
  })
  const toggle = (i: number, keep: boolean) => setUnticked((s) => {
    const next = new Set(s)
    if (keep) next.delete(i)
    else next.add(i)
    return next
  })
  return (
    <StepPanel title={`${step} · Check what Claude understood (${items.length})`} testId="setup-proposals">
      <Text size="sm" c="dimmed">Untick anything that's wrong; it stays as a draft you can fix on the Glossary page.</Text>
      <Stack gap={8}>
        {items.map((p) => (
          <Checkbox key={p.index} checked={!unticked.has(p.index)} onChange={(e) => toggle(p.index, e.currentTarget.checked)}
                    data-testid={`setup-proposal-${p.index}`}
                    label={<><b>{p.term}</b> — {p.meaning}</>} description={p.in_data || undefined} />
        ))}
      </Stack>
      <Group>
        <Button onClick={() => confirm.mutate()} loading={confirm.isPending} data-testid="setup-confirm">Confirm</Button>
      </Group>
      <ErrorNote error={confirm.error} />
    </StepPanel>
  )
}

// ---------------------------------------------------------------- the whole setup --

export default function CubeSetup({ cube, info, label }: { cube: string; info?: CubeInfo; label: string }) {
  const qc = useQueryClient()
  const setup = useCubeSetup(cube)
  const refresh = () => {
    for (const key of [['cube-setup', cube], ['cubes'], ['glossary', cube], ['info']]) void qc.invalidateQueries({ queryKey: key })
  }
  const readJob = useCubeJob(`read:${cube}`, refresh)
  const draftJob = useCubeJob(`draft:${cube}`, refresh)
  const read = useMutation({
    mutationFn: () => api.post<{ job: string }>(`/cubes/${enc(cube)}/setup/read`),
    onSuccess: ({ job }) => readJob.start(job),
  })
  const draft = useMutation({
    mutationFn: () => api.post<{ job: string }>(`/cubes/${enc(cube)}/setup/draft`),
    onSuccess: ({ job }) => draftJob.start(job),
  })
  // the cube's example questions (GET /info?scope=cube); suggested charts come with the setup, if sent
  const examples = useQuery<Info>({
    queryKey: ['info', 'scope', cube], queryFn: () => api.get<Info>(`/info?scope=${enc(cube)}`),
  })

  if (setup.isLoading) return <Text size="sm" c="dimmed">Loading…</Text>
  if (setup.error) return <ErrorNote error={setup.error} />
  const state = setup.data
  const progress = setupProgress(state, !!info?.ready)
  const reading = isActive(readJob.progress) || read.isPending
  const drafting = isActive(draftJob.progress) || draft.isPending
  const questions = openQuestions(state)
  const proposals = openProposals(state)
  const exampleQuestions = state?.example_questions ?? examples.data?.example_questions ?? []
  const charts = state?.suggested_charts ?? []

  return (
    <Stack gap="md" data-testid="cube-setup">
      <StepPanel title="1 · Read the structure and values" testId="setup-step1">
        {progress.structure ? (
          <Done>
            Done{state?.structure_read ? ` (${state.structure_read})` : ''}. Read again after the cube changes (new measures,
            columns or values).
          </Done>
        ) : (
          <Text size="sm" c="dimmed">
            Reads every table, measure, column and value (with how much data each has). About a minute for a large cube.
          </Text>
        )}
        <Group>
          <Button variant={progress.structure ? 'default' : 'filled'} leftSection={<SyncIcon size={16} />}
                  onClick={() => read.mutate()} loading={read.isPending} disabled={reading || drafting}
                  data-testid="setup-read">
            {progress.structure ? 'Read again' : 'Read structure and values'}
          </Button>
        </Group>
        <ErrorNote error={read.error} />
        {readJob.id && (
          <JobLog progress={readJob.progress} testId="setup-read-job" onHide={readJob.hide}
                  words={{ running: `Reading ${label}...`, done: `${label} is read`, failed: `${label} could not be read` }} />
        )}
      </StepPanel>

      {progress.structure && (
        <StepPanel title="2 · Let Claude map your business words" testId="setup-step2">
          {progress.drafted ? (
            <Done>{state?.summary || 'The map is drafted.'}{state?.drafted && <> (drafted {whenText(state.drafted)})</>}</Done>
          ) : (
            <Text size="sm" c="dimmed">
              Claude reads the structure and values and works out what words like <i>bookings</i>, <i>sales</i> or
              {' '}<i>destination</i> mean in this cube. About a minute.
            </Text>
          )}
          <Group>
            <Button variant={progress.drafted ? 'default' : 'filled'} leftSection={<SparkIcon size={16} />}
                    onClick={() => draft.mutate()} loading={draft.isPending} disabled={drafting || reading}
                    data-testid="setup-draft">
              {progress.drafted ? 'Map again' : 'Map the business words'}
            </Button>
          </Group>
          <ErrorNote error={draft.error} />
          {draftJob.id && (
            <JobLog progress={draftJob.progress} testId="setup-draft-job" onHide={draftJob.hide}
                    words={{ running: 'Claude is reading the cube and drafting the map...', done: 'The map is drafted',
                             failed: 'The map could not be drafted' }} />
          )}
        </StepPanel>
      )}

      {progress.structure && progress.drafted && !drafting && (
        <>
          {questions.length > 0 && (
            <Stack gap="sm" data-testid="setup-questions">
              <Stack gap={2}>
                <Text fw={600}>3 · A few questions ({questions.length})</Text>
                <Text size="sm" c="dimmed">
                  Your answers become the agreed meaning everyone's questions use. Not sure? Skip it - Chat will ask
                  whoever needs it.
                </Text>
              </Stack>
              {questions.map((q) => <SetupQuestion key={`${cube}-${q.index}`} cube={cube} item={q} />)}
            </Stack>
          )}
          {proposals.length > 0 && (
            <SetupProposals key={`${cube}-${proposals.map((p) => p.index).join(',')}`} cube={cube}
                            step={questions.length ? 4 : 3} items={proposals} />
          )}
          {!questions.length && !proposals.length && (
            <Alert color="teal" icon={<CheckIcon />} data-testid="setup-ready">
              <Text size="sm">
                <b>{label} is ready.</b> People can ask about it in Chat; the agreed meanings are on the Glossary page.
              </Text>
              <Group gap="lg" mt="xs">
                <Anchor component={Link} to="/chat" size="sm">Ask a question</Anchor>
                <Anchor component={Link} to={`/glossary?cube=${enc(cube)}`} size="sm">See the Glossary</Anchor>
              </Group>
            </Alert>
          )}
        </>
      )}

      {(exampleQuestions.length > 0 || charts.length > 0) && (
        <StepPanel title="Suggested for this cube" testId="setup-suggestions">
          {exampleQuestions.length > 0 && (
            <>
              <Text size="sm" c="dimmed">Example questions people can ask in Chat:</Text>
              <List size="sm" spacing={2} data-testid="setup-example-questions">
                {exampleQuestions.map((q) => <List.Item key={q}>{q}</List.Item>)}
              </List>
            </>
          )}
          {charts.length > 0 && (
            <>
              <Text size="sm" c="dimmed" mt={exampleQuestions.length ? 'xs' : 0}>Suggested dashboard charts:</Text>
              <List size="sm" spacing={2}>
                {charts.map((c) => (
                  <List.Item key={c.title}>
                    <b>{c.title}</b> — {c.question}{' '}
                    <Text span size="xs" c="dimmed">({c.chart_type.replace(/_/g, ' ')})</Text>
                  </List.Item>
                ))}
              </List>
            </>
          )}
        </StepPanel>
      )}
    </Stack>
  )
}
