// "Add to a dashboard": pick a dashboard (or make a new one), a title, a size and how the chart's dates
// work there, then the answer is added as it was drawn here (POST /dashboards/{id}/charts/from-answer:
// no Claude call and no query when it can be done in code). Admins only (views/chat.py add_to_dashboard).
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Anchor, Button, Group, Loader, Modal, Radio, SegmentedControl, Select, Stack, Text, TextInput } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { api } from '../../api/client'
import type { ChartMeta, Dashboard, DashboardSummary, PeriodMode } from '../../api/types'
import SignInButton from '../auth/SignInButton'
import { useSession } from '../auth/useSession'
import { ALL_DATES_LABEL, defaultTitle, defaultWidth, periodChoices } from './periodChoices'
import type { TurnView } from './types'

const NEW = '__new__'

type Props = { turn: TurnView | null; conversationId: string | null; onClose: () => void }

export default function AddToDashboardModal({ turn, conversationId, onClose }: Props) {
  return (
    <Modal opened={!!turn} onClose={onClose} title="Add to a dashboard" size="lg" data-testid="chat-add-modal">
      {turn && <AddForm key={turn.key} turn={turn} conversationId={conversationId} onClose={onClose} />}
    </Modal>
  )
}

function AddForm({ turn, conversationId, onClose }: { turn: TurnView; conversationId: string | null; onClose: () => void }) {
  const { isAdmin, isLoading } = useSession()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const boards = useQuery<DashboardSummary[]>({
    queryKey: ['dashboards'], queryFn: () => api.get<DashboardSummary[]>('/dashboards'), enabled: isAdmin,
  })
  const choices = useMemo(() => periodChoices(turn), [turn])
  const [target, setTarget] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [title, setTitle] = useState(() => defaultTitle(turn))
  const [width, setWidth] = useState<'half' | 'full'>(() => defaultWidth(turn))
  const [mode, setMode] = useState<PeriodMode>(choices[0].mode)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [added, setAdded] = useState<{ id: string; name: string; title: string } | null>(null)

  // the first dashboard by default, or a new one when there is none yet
  useEffect(() => {
    if (target === null && boards.data) setTarget(boards.data[0]?.id ?? NEW)
  }, [boards.data, target])

  if (isLoading) return <Loader size="sm" />
  if (!isAdmin) {
    return (
      <Stack gap="sm" data-testid="chat-add-signin">
        <Text size="sm" c="dimmed">Only admins can change the shared dashboards.</Text>
        <SignInButton label="Sign in as admin" variant="button" />
      </Stack>
    )
  }

  const openBoard = (id: string) => { onClose(); navigate(`/dashboard/${id}`) }

  if (added) {
    return (
      <Stack gap="sm" data-testid="chat-add-done">
        <Alert color="green" variant="light">
          Added <strong>{added.title}</strong> to <strong>{added.name}</strong>.
        </Alert>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Close</Button>
          <Button onClick={() => openBoard(added.id)} data-testid="chat-add-open">Open the dashboard</Button>
        </Group>
      </Stack>
    )
  }

  const choice = choices.find(c => c.mode === mode) ?? choices[0]
  const isNew = target === NEW
  const options = [...(boards.data ?? []).map(b => ({ value: b.id, label: b.name })), { value: NEW, label: 'New dashboard…' }]

  async function add() {
    if (!target || !conversationId || !turn.id) return
    setSaving(true)
    setError(null)
    let boardId = target, boardName = boards.data?.find(b => b.id === target)?.name ?? '', created = false
    try {
      if (isNew) {
        const board = await api.post<Dashboard>('/dashboards', { name: name.trim() })
        boardId = board.id
        boardName = board.name
        created = true
      }
      const chart = await api.post<ChartMeta>(`/dashboards/${boardId}/charts/from-answer`, {
        conversation_id: conversationId, turn_id: turn.id, period_mode: mode, title: title.trim() || undefined, width,
      })
      queryClient.invalidateQueries({ queryKey: ['dashboards'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard', boardId] })
      queryClient.invalidateQueries({ queryKey: ['results', boardId] })
      setAdded({ id: boardId, name: boardName, title: chart.title })
      notifications.show({
        color: 'green',
        title: 'Added to the dashboard',
        message: (
          <span data-testid="chat-add-notification">
            Added <strong>{chart.title}</strong> to <strong>{boardName}</strong>.{' '}
            <Anchor href={`/dashboard/${boardId}`} size="sm"
                    onClick={e => { e.preventDefault(); openBoard(boardId) }}>Open the dashboard</Anchor>
          </span>
        ),
      })
    } catch (err) {
      setError((err as Error).message || 'The chart could not be added.')
      if (created) api.del(`/dashboards/${boardId}`).catch(() => undefined) // don't leave an empty new dashboard behind
    } finally {
      setSaving(false)
    }
  }

  return (
    <Stack gap="md">
      <Select label="Dashboard" data={options} value={target} onChange={v => setTarget(v)} allowDeselect={false}
              disabled={boards.isLoading} placeholder={boards.isLoading ? 'Loading…' : undefined}
              data-testid="chat-add-dashboard" comboboxProps={{ withinPortal: true }} />
      {boards.isError && (
        <Alert color="red" variant="light">The dashboards could not be read: {(boards.error as Error).message}</Alert>
      )}
      {isNew && (
        <TextInput label="Name of the new dashboard" value={name} onChange={e => setName(e.currentTarget.value)}
                   data-testid="chat-add-name" autoFocus />
      )}
      <TextInput label="Title" value={title} onChange={e => setTitle(e.currentTarget.value)} data-testid="chat-add-title" />
      <Radio.Group label="Dates" value={mode} onChange={v => setMode(v as PeriodMode)} data-testid="chat-add-period"
                   description="Own period: the dates of your question, worked out again every day (yesterday stays yesterday). Fixed dates: never move. Follow the dashboard: the period picked there.">
        <Stack gap={6} mt={6}>
          {choices.map(c => (
            <Radio key={c.mode} value={c.mode} label={c.label} data-testid={`chat-add-period-${c.mode}`} />
          ))}
        </Stack>
      </Radio.Group>
      <div>
        <Text size="sm" fw={500} mb={4}>Size</Text>
        <SegmentedControl value={width} onChange={v => setWidth(v as 'half' | 'full')} data-testid="chat-add-width"
                          data={[{ value: 'half', label: 'Half width' }, { value: 'full', label: 'Full width' }]} />
      </div>
      {!choice.instant && (
        <Text size="xs" c="dimmed" data-testid="chat-add-slow">
          Claude rewrites the query for the dashboard's period and tests it (about half a minute).
          {!turn.periods.length && <> Or pick <strong>{ALL_DATES_LABEL}</strong> to add it at once.</>}
        </Text>
      )}
      {error && <Alert color="red" variant="light" data-testid="chat-add-error">{error}</Alert>}
      <Group justify="flex-end">
        <Button variant="default" onClick={onClose} disabled={saving}>Cancel</Button>
        <Button onClick={add} loading={saving} data-testid="chat-add-submit"
                disabled={!target || (isNew && !name.trim()) || !conversationId || !turn.id}>
          Add to dashboard
        </Button>
      </Group>
      {saving && !choice.instant && (
        <Text size="xs" c="dimmed">Preparing the chart for the dashboard and testing it...</Text>
      )}
    </Stack>
  )
}
