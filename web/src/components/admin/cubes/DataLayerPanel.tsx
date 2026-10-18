// "Data layer": when it was built, which cubes are missing or changed, the meaning layer's drift, and the
// buttons that build or update it (POST /layer/build → a job whose progress streams in below).
import { Alert, Anchor, Button, Group, Paper, Stack, Text, Tooltip } from '@mantine/core'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../../../api/client'
import ErrorNote from '../ErrorNote'
import JobLog from '../JobLog'
import { cubeLabeller } from '../cubeHelpers'
import { plural } from '../format'
import { CheckIcon, InfoIcon, SyncIcon, WarnIcon } from '../icons'
import { useAdminJobs } from '../jobStore'
import { isActive } from '../jobProgress'
import { useJobProgress } from '../useJobProgress'
import type { DecisionsData } from '../queries'
import type { CubesData } from '../types'

export const LAYER_JOB = 'layer'

export default function DataLayerPanel({ data, decisions, layerModel }: {
  data: CubesData; decisions?: DecisionsData; layerModel?: string
}) {
  const qc = useQueryClient()
  const label = cubeLabeller(data)
  const layer = data.layer ?? { built: '', model: '', cubes: [], missing: [], changed: [], entities: 0, ready: false }
  const jobId = useAdminJobs((s) => s.jobs[LAYER_JOB])
  const setJob = useAdminJobs((s) => s.setJob)
  const clearJob = useAdminJobs((s) => s.clearJob)

  const build = useMutation({
    mutationFn: (onlyChanged: boolean) => api.post<{ job: string }>('/layer/build', { cubes: null, only_changed: onlyChanged }),
    onSuccess: ({ job }) => setJob(LAYER_JOB, job),
  })
  const progress = useJobProgress(jobId ?? null, () => {
    for (const key of ['cubes', 'info', 'cube-setup', 'decisions']) void qc.invalidateQueries({ queryKey: [key] })
  })

  const running = isActive(progress)
  // the meaning layer's decisions: counted by the server if it says, else from the decisions list
  const meaning = data.meaning ?? (decisions
    ? { decisions: decisions.items.length, agreed: decisions.items.filter((d) => d.status === 'agreed').length }
    : null)
  const model = data.layer_model || layerModel
  const needsUpdate = layer.missing.length > 0 || layer.changed.length > 0

  return (
    <Paper withBorder p="md" radius="md" data-testid="layer-status">
      <Stack gap="sm">
        {layer.built ? (
          <Group gap={8} wrap="nowrap" align="flex-start">
            <Text c="teal" span lh={0} mt={2}><CheckIcon /></Text>
            <Text size="sm">
              <b>Built</b> {layer.built.replace('T', ' ').slice(0, 16)}{layer.model && <> with <code>{layer.model}</code></>}
              {' · '}{plural(layer.cubes.length, 'cube')} · {plural(layer.entities, 'shared dimension')}
            </Text>
          </Group>
        ) : (
          <Text size="sm">
            <b>Build it once after installing.</b> Claude reads every connected cube (structure and every value), learns
            what each one is for, what its numbers and dates mean, and which customers, suppliers, hotels... are the
            same across cubes, so it can pick the right cube and join cubes in one answer. Chat and the dashboards then
            work from it.
          </Text>
        )}

        {layer.built && layer.missing.length > 0 && (
          <Alert color="yellow" icon={<WarnIcon />} data-testid="layer-missing">
            {plural(layer.missing.length, 'connected cube')} {layer.missing.length === 1 ? 'is' : 'are'} not in the data
            layer yet: {layer.missing.map(label).join(', ')}. Update it to add them.
          </Alert>
        )}
        {layer.built && layer.changed.length > 0 && (
          <Alert color="yellow" icon={<SyncIcon />} data-testid="layer-changed">
            {plural(layer.changed.length, 'cube')} changed since the layer was built: {layer.changed.map(label).join(', ')}.
            {' '}Update it.
          </Alert>
        )}
        {layer.built && (data.drift?.length ?? 0) > 0 && (
          <Alert color="yellow" icon={<WarnIcon />} data-testid="layer-drift">
            The meaning layer (semantic/) was built for an earlier structure of {plural(data.drift.length, 'cube')}:
            {' '}{data.drift.map(label).join(', ')}. Answers still work; ask for the meaning layer to be checked for
            these cubes (python semantic.py facts, then check).
          </Alert>
        )}
        {layer.built && !(data.drift?.length) && meaning && (
          <Group gap={6} wrap="nowrap">
            <Text c="dimmed" span lh={0}><InfoIcon size={16} /></Text>
            <Text size="sm" c="dimmed">
              Meaning layer: {plural(meaning.decisions, 'decision')}, {meaning.agreed} agreed
              (<Anchor component={Link} to="/glossary" size="sm">Glossary › Decisions</Anchor>).
            </Text>
          </Group>
        )}

        <Text size="xs" c="dimmed">
          Reading takes about a minute per cube; then Claude{model ? ` (${model})` : ''} studies them. Run it
          again after cubes change.
        </Text>
        <Group gap="sm">
          <Button variant={layer.built ? 'default' : 'filled'} loading={build.isPending && build.variables === false}
                  disabled={running || build.isPending} onClick={() => build.mutate(false)} data-testid="layer-build">
            {layer.built ? 'Rebuild the data layer' : 'Build the data layer'}
          </Button>
          {layer.built && (
            <Tooltip label="Reads every cube again, and asks Claude only about the cubes that are new or changed." multiline w={280}>
              <Button variant={needsUpdate ? 'filled' : 'default'} leftSection={<SyncIcon size={16} />}
                      loading={build.isPending && build.variables === true}
                      disabled={running || build.isPending} onClick={() => build.mutate(true)} data-testid="layer-update">
                Update new and changed cubes
              </Button>
            </Tooltip>
          )}
        </Group>
        <ErrorNote error={build.error} />
        {jobId && (
          <JobLog progress={progress} testId="layer-job" onHide={() => clearJob(LAYER_JOB)}
                  words={{ running: 'Building the data layer...', done: 'Data layer ready',
                           failed: 'The data layer could not be built' }} />
        )}
      </Stack>
    </Paper>
  )
}
