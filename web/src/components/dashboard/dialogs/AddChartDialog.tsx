// "Add a chart": describe it in plain English; Claude builds the query and the chart (the slow path).
import { useState } from 'react'
import { Button, Group, Modal, Stack, Text, TextInput, Textarea } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { useDashboardActions, useRunner, type NewChart } from '../../../lib/dashboardActions'
import { errorDetails, errorText, notifyDone } from '../../../lib/notify'
import { infoQuery } from '../../../lib/queries'
import { AUTO_DATE } from '../../../lib/labels'
import AdminGate from '../../auth/AdminGate'
import ErrorNote from '../../ErrorNote'
import { ChartRequestField, ChartTypeField, CubeField, DateColumnField, PeriodModeField, WidthField } from './fields'

type Props = { opened: boolean; onClose: () => void; dashboardId: string }

export default function AddChartDialog({ opened, onClose, dashboardId }: Props) {
  return (
    <Modal opened={opened} onClose={onClose} title={<b>Add a chart</b>} size="lg">
      <AdminGate what="adding a chart">
        {opened && <AddChartForm dashboardId={dashboardId} onClose={onClose} />}
      </AdminGate>
    </Modal>
  )
}

function AddChartForm({ dashboardId, onClose }: { dashboardId: string; onClose: () => void }) {
  const { data: info } = useQuery(infoQuery)
  const actions = useDashboardActions()
  const { busy, error, run } = useRunner()
  const [cube, setCube] = useState(info?.scopes[0]?.value ?? '') // as the old picker: its first choice
  const [question, setQuestion] = useState('')
  const [title, setTitle] = useState('')
  const [chartType, setChartType] = useState('auto')
  const [request, setRequest] = useState('')
  const [dateColumn, setDateColumn] = useState(AUTO_DATE)
  const [width, setWidth] = useState<'half' | 'full'>('half')
  const [periodMode, setPeriodMode] = useState<NewChart['period_mode']>('dashboard')

  const custom = chartType === 'custom'
  const ready = question.trim() && (!custom || request.trim())

  const create = async () => {
    const chart: NewChart = {
      question: question.trim(), title: title.trim(), chart_type: chartType, width, cube, date_column: dateColumn,
      period_mode: periodMode, ...(custom ? { chart_request: request.trim() } : {}),
    }
    const made = await run(() => actions.addChart(dashboardId, chart))
    if (made) {
      notifyDone(`Added "${made.title}".`)
      onClose()
    }
  }

  return (
    <Stack gap="sm">
      <CubeField info={info} value={cube} onChange={setCube} />
      <Textarea label="What should the chart show?" value={question} autosize minRows={2} data-autofocus
                onChange={(e) => setQuestion(e.currentTarget.value)}
                placeholder={`e.g. Top 10 destination countries by sales${cube === '' ? ', or sales and payments by customer' : ''}`} />
      <TextInput label="Title" placeholder="Optional - Claude suggests one" value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
      <ChartTypeField value={chartType} allowAuto onChange={(t) => { setChartType(t); if (t === 'custom') setWidth('full') }} />
      {custom && <ChartRequestField value={request} onChange={setRequest} />}
      <DateColumnField info={info} cube={cube} value={dateColumn} onChange={setDateColumn} />
      <PeriodModeField value={periodMode} onChange={setPeriodMode} />
      <WidthField value={width} onChange={setWidth} />
      {error ? <ErrorNote message={errorText(error)} details={errorDetails(error)} /> : null}
      <Group justify="space-between" mt="xs">
        <Text size="sm" c="dimmed">{busy ? 'Claude is checking the data, writing the query and testing it...' : ''}</Text>
        <Button onClick={create} loading={busy} disabled={!ready} data-testid="create-chart">Create chart</Button>
      </Group>
    </Stack>
  )
}
