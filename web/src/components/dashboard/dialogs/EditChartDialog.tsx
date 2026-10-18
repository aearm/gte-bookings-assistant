// "Edit chart": title, type, size, dates (follow the dashboard / own period / fixed), the date the
// period filters, the comparison, and the question (a new question asks Claude for a new query).
import { useState } from 'react'
import { Button, Group, Modal, Stack, Switch, Text, TextInput, Textarea } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import type { ChartMeta } from '../../../api/types'
import { useDashboardActions, useRunner, type ChartChanges } from '../../../lib/dashboardActions'
import { errorDetails, errorText } from '../../../lib/notify'
import { infoQuery } from '../../../lib/queries'
import ErrorNote from '../../ErrorNote'
import { ChartRequestField, ChartTypeField, DateColumnField, PeriodModeField, WidthField } from './fields'

type Props = { chart: ChartMeta | null; onClose: () => void; dashboardId: string; cubeLabel: (cube: string) => string }

export default function EditChartDialog({ chart, onClose, dashboardId, cubeLabel }: Props) {
  return (
    <Modal opened={!!chart} onClose={onClose} title={<b>Edit chart</b>} size="lg">
      {chart && <EditForm key={chart.id} chart={chart} dashboardId={dashboardId} onClose={onClose} cubeLabel={cubeLabel} />}
    </Modal>
  )
}

function EditForm({ chart, dashboardId, onClose, cubeLabel }: { chart: ChartMeta; dashboardId: string; onClose: () => void; cubeLabel: (c: string) => string }) {
  const { data: info } = useQuery(infoQuery)
  const actions = useDashboardActions()
  const { busy, error, run } = useRunner()
  const [title, setTitle] = useState(chart.title)
  const [question, setQuestion] = useState(chart.question)
  const [chartType, setChartType] = useState(chart.chart_type === 'pie' ? 'donut' : chart.chart_type)
  const [request, setRequest] = useState('')
  const [width, setWidth] = useState<'half' | 'full'>(chart.width)
  const [mode, setMode] = useState(chart.period?.mode ?? 'dashboard')
  const [dateColumn, setDateColumn] = useState(chart.date_column ?? '')
  const [compare, setCompare] = useState(chart.compares !== false)

  const cube = chart.cubes.length === 1 ? chart.cubes[0] : ''
  const newQuestion = question.trim() !== chart.question.trim()
  const compareAllowed = mode === 'dashboard' && !!dateColumn

  const save = async () => {
    const changes: ChartChanges = {}
    if (title.trim() && title.trim() !== chart.title) changes.title = title.trim()
    if (newQuestion) changes.question = question.trim()
    if (chartType !== chart.chart_type) changes.chart_type = chartType
    if (chartType === 'custom' && request.trim()) changes.chart_request = request.trim()
    if (width !== chart.width) changes.width = width
    if (mode !== chart.period?.mode) changes.period_mode = mode
    if (mode === 'dashboard' && dateColumn !== (chart.date_column ?? '')) changes.date_column = dateColumn
    if (compare !== (chart.compares !== false)) changes.compare = compare
    if (!Object.keys(changes).length) return onClose()
    const saved = await run(() => actions.updateChart(dashboardId, chart.id, changes))
    if (saved) onClose()
  }

  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">Data: {chart.cubes.map(cubeLabel).join(' + ') || '—'}</Text>
      <TextInput label="Title" value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
      <Textarea label="What the chart shows" value={question} autosize minRows={2}
                description="Changing this asks Claude to write a new query." onChange={(e) => setQuestion(e.currentTarget.value)} />
      <ChartTypeField value={chartType} allowAuto={false} onChange={setChartType} />
      {chartType === 'custom' && <ChartRequestField value={request} onChange={setRequest} />}
      <PeriodModeField value={mode} onChange={setMode} current={chart.period} />
      {mode === 'dashboard' && <DateColumnField info={info} cube={cube} value={dateColumn} onChange={setDateColumn} />}
      <Switch label="Show the comparison picked at the top of the dashboard" checked={compare && compareAllowed}
              disabled={!compareAllowed} onChange={(e) => setCompare(e.currentTarget.checked)}
              description="Headline numbers show the change; columns, bars and lines of one measure show the other period in grey; tables get a change column. Needs dates that follow the dashboard." />
      <WidthField value={width} onChange={setWidth} />
      {error ? <ErrorNote message={errorText(error)} details={errorDetails(error)} /> : null}
      <Group justify="space-between" mt="xs">
        <Text size="sm" c="dimmed">{busy && newQuestion ? 'Claude is writing a new query and testing it...' : ''}</Text>
        <Button onClick={save} loading={busy} disabled={chartType === 'custom' && chart.chart_type !== 'custom' && !request.trim()}>
          Save changes
        </Button>
      </Group>
    </Stack>
  )
}
