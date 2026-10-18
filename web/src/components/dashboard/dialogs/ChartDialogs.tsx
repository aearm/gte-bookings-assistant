// The smaller chart dialogs: change how it looks, send to another dashboard, delete.
import { useState } from 'react'
import { Button, Group, Modal, Radio, Select, Stack, Text, TextInput } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import type { ChartMeta } from '../../../api/types'
import { useDashboardActions, useRunner } from '../../../lib/dashboardActions'
import { errorDetails, errorText, notifyDone } from '../../../lib/notify'
import { dashboardsQuery } from '../../../lib/queries'
import ErrorNote from '../../ErrorNote'
import { ChartRequestField } from './fields'

type Props = { chart: ChartMeta | null; onClose: () => void; dashboardId: string }

function Problem({ error }: { error: unknown }) {
  return error ? <ErrorNote message={errorText(error)} details={errorDetails(error)} /> : null
}

export function RestyleDialog({ chart, onClose, dashboardId }: Props) {
  return (
    <Modal opened={!!chart} onClose={onClose} title={<b>Change how the chart looks</b>} size="lg">
      {chart && <RestyleForm key={chart.id} chart={chart} onClose={onClose} dashboardId={dashboardId} />}
    </Modal>
  )
}

function RestyleForm({ chart, onClose, dashboardId }: Props & { chart: ChartMeta }) {
  const actions = useDashboardActions()
  const { busy, error, run } = useRunner()
  const [request, setRequest] = useState('')
  const draw = async () => {
    if (await run(() => actions.restyleChart(dashboardId, chart.id, request.trim()))) onClose()
  }
  return (
    <Stack gap="sm">
      <Text size="sm"><b>{chart.title}</b> · same numbers, drawn the way you describe.</Text>
      <ChartRequestField value={request} onChange={setRequest} />
      <Problem error={error} />
      <Group justify="space-between">
        <Text size="sm" c="dimmed">{busy ? 'Claude is drawing the chart you described...' : ''}</Text>
        <Button onClick={draw} loading={busy} disabled={!request.trim()}>Draw it</Button>
      </Group>
    </Stack>
  )
}

const NEW = '__new__'

export function SendDialog({ chart, onClose, dashboardId }: Props) {
  return (
    <Modal opened={!!chart} onClose={onClose} title={<b>Send to another dashboard</b>}>
      {chart && <SendForm key={chart.id} chart={chart} onClose={onClose} dashboardId={dashboardId} />}
    </Modal>
  )
}

function SendForm({ chart, onClose, dashboardId }: Props & { chart: ChartMeta }) {
  const { data: boards } = useQuery(dashboardsQuery)
  const actions = useDashboardActions()
  const { busy, error, run } = useRunner()
  const others = (boards ?? []).filter((b) => b.id !== dashboardId)
  const [target, setTarget] = useState<string>(others[0]?.id ?? NEW)
  const [name, setName] = useState('')
  const [how, setHow] = useState<'copy' | 'move'>('copy')
  const send = async () => {
    const done = await run(async () => {
      const to = target === NEW ? (await actions.createDashboard(name || 'New dashboard')).id : target
      await actions.sendChart(dashboardId, chart.id, to, how === 'move')
      return true
    })
    if (done) {
      notifyDone(how === 'move' ? `Moved "${chart.title}".` : `Copied "${chart.title}".`)
      onClose()
    }
  }
  return (
    <Stack gap="sm">
      <Text size="sm"><b>{chart.title}</b></Text>
      <Select label="Dashboard" value={target} allowDeselect={false} onChange={(v) => v && setTarget(v)}
              data={[...others.map((b) => ({ value: b.id, label: b.name })), { value: NEW, label: '+ New dashboard…' }]} />
      {target === NEW && <TextInput label="Name of the new dashboard" value={name} onChange={(e) => setName(e.currentTarget.value)} />}
      <Radio.Group value={how} onChange={(v) => setHow(v as 'copy' | 'move')}>
        <Stack gap={6}>
          <Radio value="copy" label="Copy (keep it here too)" />
          <Radio value="move" label="Move (remove it from here)" />
        </Stack>
      </Radio.Group>
      <Problem error={error} />
      <Group justify="flex-end">
        <Button onClick={send} loading={busy} disabled={target === NEW && !name.trim()}>Send</Button>
      </Group>
    </Stack>
  )
}

export function DeleteChartDialog({ chart, onClose, dashboardId }: Props) {
  const actions = useDashboardActions()
  const { busy, error, run, reset } = useRunner()
  const close = () => { reset(); onClose() }
  const remove = async () => {
    if (!chart) return
    await run(async () => {
      await actions.deleteChart(dashboardId, chart.id)
      close()
    })
  }
  return (
    <Modal opened={!!chart} onClose={close} title={<b>Delete chart</b>}>
      <Stack gap="sm">
        <Text size="sm">Delete <b>{chart?.title ?? 'this chart'}</b> from the dashboard for everyone?</Text>
        <Problem error={error} />
        <Group justify="flex-end">
          <Button variant="default" onClick={close}>Cancel</Button>
          <Button color="red" onClick={remove} loading={busy} data-testid="confirm-delete-chart">Delete</Button>
        </Group>
      </Stack>
    </Modal>
  )
}
