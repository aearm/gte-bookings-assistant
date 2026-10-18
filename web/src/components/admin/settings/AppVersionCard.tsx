// "App version": the version running, the newest one on GitHub (GET /updates; "Check for updates" asks
// GitHub afresh), what's new, and updating (POST /updates/apply). While the app stops, updates and starts
// again, the page asks /health every few seconds and says when the new version is running.
import { useEffect, useState } from 'react'
import { Alert, Anchor, Button, Group, Loader, Paper, Stack, Text, Title } from '@mantine/core'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../../api/client'
import ErrorNote from '../ErrorNote'
import { CheckIcon, ErrorIcon, InfoIcon, SyncIcon } from '../icons'
import { useUpdates } from '../queries'
import type { Health, UpdatesInfo } from '../types'
import { checkResult, describeUpdateStatus, idleWatch, startWatch, stepWatch, watchText, type UpdateWatch } from '../updateWatch'

const PROBE_MS = 3000

/** Is the server up, which version, and (while the old one still runs) did the download fail? */
async function probe(from: string): Promise<{ ok: boolean; version?: string; error?: string }> {
  let health: Health
  try {
    health = await api.get<Health>('/health')
  } catch {
    return { ok: false }   // stopped or restarting
  }
  if (health.ok && health.version === from) {
    try {
      const u = await api.get<UpdatesInfo>('/updates')
      if (u.status !== 'updating' && u.error) return { ok: true, version: health.version, error: u.error }
    } catch { /* ask again next time */ }
  }
  return { ok: !!health.ok, version: health.version }
}

function useUpdateWatch(): [UpdateWatch, (from: string, to: string) => void] {
  const [watch, setWatch] = useState<UpdateWatch>(idleWatch)
  const following = watch.phase === 'waiting' || watch.phase === 'restarting' || watch.phase === 'slow'
  const from = watch.from
  useEffect(() => {
    if (!following) return
    let stop = false
    const timer = setInterval(async () => {
      const answer = await probe(from)
      if (!stop) setWatch((w) => stepWatch(w, answer, Date.now()))
    }, PROBE_MS)
    return () => { stop = true; clearInterval(timer) }
  }, [following, from])
  return [watch, (a, b) => setWatch(startWatch(a, b, Date.now()))]
}

export default function AppVersionCard({ version }: { version?: string }) {
  const qc = useQueryClient()
  const updates = useUpdates(true)
  const [checked, setChecked] = useState(false)
  const check = useMutation({
    mutationFn: () => api.get<UpdatesInfo>('/updates?fresh=true'),
    onSuccess: (data) => { qc.setQueryData(['updates'], data); setChecked(true) },
  })
  const [watch, follow] = useUpdateWatch()
  const info = updates.data
  const current = info?.current || version || ''
  const latest = info?.latest || ''
  const apply = useMutation({
    mutationFn: () => api.post<{ started: boolean; version?: string }>('/updates/apply'),
    onSuccess: (r) => follow(current, r?.version || latest),
  })

  const result = info ? checkResult(info) : null
  const last = describeUpdateStatus(info?.last ?? (info && typeof info.status === 'object' ? info.status : null))
  const updating = result === 'updating' || watch.phase !== 'idle'
  const failedDownload = info && result !== 'failed' && result !== 'updating' && info.error

  return (
    <Stack gap="sm" data-testid="app-version">
      <Text fw={600} data-testid="app-version-current">Bookings Assistant {current || '…'}</Text>
      {last?.kind === 'ok' && <Text size="sm" c="dimmed" data-testid="updates-last">{last.text}</Text>}
      {last?.kind === 'failed' && <Alert color="red" icon={<ErrorIcon />} data-testid="updates-last">{last.text}</Alert>}

      {watch.phase !== 'idle' ? (
        <Alert data-testid="updates-progress" data-phase={watch.phase}
               color={watch.phase === 'done' ? 'teal' : watch.phase === 'failed' ? 'red' : watch.phase === 'slow' ? 'yellow' : 'blue'}
               icon={watch.phase === 'done' ? <CheckIcon /> : watch.phase === 'failed' ? <ErrorIcon />
                 : watch.phase === 'slow' ? <InfoIcon /> : <Loader size={16} />}>
          <Stack gap="xs">
            <Text size="sm">{watchText(watch)}</Text>
            {(watch.phase === 'done' || watch.phase === 'slow') && (
              <Group>
                <Button size="xs" onClick={() => window.location.reload()} data-testid="updates-reload">Reload the page</Button>
              </Group>
            )}
          </Stack>
        </Alert>
      ) : result === 'updating' ? (
        <Alert color="blue" icon={<Loader size={16} />} data-testid="updates-progress" data-phase="running">
          An update is running: the app stops, updates and starts again by itself (about a minute). This page reconnects
          when it's back.
        </Alert>
      ) : null}

      {!updating && (
        <Group>
          <Button variant="default" leftSection={<SyncIcon size={16} />} onClick={() => check.mutate()}
                  loading={check.isPending} data-testid="updates-check">
            Check for updates
          </Button>
          {updates.isFetching && !check.isPending && <Loader size="xs" />}
        </Group>
      )}
      <ErrorNote error={check.error} testId="updates-error" />
      {failedDownload && !updating && (
        <Alert color="red" icon={<ErrorIcon />} data-testid="updates-download-error">The update didn't work: {info.error}</Alert>
      )}

      {info && !updating && !check.isPending && (
        result === 'failed' ? (
          // a failed check is only worth saying when the admin asked
          checked && <Alert color="red" icon={<ErrorIcon />} data-testid="updates-result" data-result="failed">
            {info.error || "Couldn't reach GitHub to check for updates."}
          </Alert>
        ) : result === 'none' ? (
          <Text size="sm" c="dimmed" data-testid="updates-result" data-result="none">No version has been published on GitHub yet.</Text>
        ) : result === 'latest' ? (
          <Alert color="teal" icon={<CheckIcon />} data-testid="updates-result" data-result="latest">
            You have the latest version ({latest || current}).
          </Alert>
        ) : (
          <Stack gap="sm" data-testid="updates-result" data-result="newer">
            <Alert color="blue" icon={<InfoIcon />}>
              <b>Version {latest}</b> is available{info.published ? ` (published ${info.published})` : ''}.
            </Alert>
            <Paper withBorder p="md" radius="md">
              <Title order={5} mb={6}>What's new</Title>
              <Text size="sm" style={{ whiteSpace: 'pre-wrap' }} data-testid="updates-notes">{info.notes || 'No description.'}</Text>
              {info.page && <Anchor href={info.page} target="_blank" rel="noreferrer" size="xs">See it on GitHub</Anchor>}
            </Paper>
            {info.developer_copy ? (
              <Text size="sm" c="dimmed" data-testid="updates-developer-copy">
                This folder is a developer copy (git), so it's updated with <b>git pull</b>, then a restart of the app -
                not from here.
              </Text>
            ) : (
              <>
                <Text size="sm" c="dimmed">
                  Kept exactly as they are: settings and keys, dashboards, the data layer, answer memory, usage and
                  history. The current version is saved in data/backup first, and put back if anything goes wrong.
                </Text>
                <Group>
                  <Button onClick={() => apply.mutate()} loading={apply.isPending} data-testid="updates-apply">
                    Update to {latest}
                  </Button>
                </Group>
              </>
            )}
          </Stack>
        )
      )}
      <ErrorNote error={apply.error} testId="updates-apply-error" />
    </Stack>
  )
}
