// "Make a dashboard from this conversation": its charts on a new dashboard of their own, in the
// conversation's order (POST /dashboards/from-conversation), then the dashboard opens. Admins only.
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Group, List, Modal, Stack, Text, TextInput } from '@mantine/core'
import { api } from '../../api/client'
import type { Dashboard } from '../../api/types'
import SignInButton from '../auth/SignInButton'
import { useSession } from '../auth/useSession'
import { DashboardIcon } from './icons'
import { defaultBoardName, defaultTitle, periodChoices } from './periodChoices'
import type { TurnView } from './types'

type Props = { turns: TurnView[]; conversationId: string | null }

export default function DashboardFromConversation({ turns, conversationId }: Props) {
  const [opened, setOpened] = useState(false)
  const n = turns.length
  return (
    <>
      <Button variant="default" leftSection={<DashboardIcon />} onClick={() => setOpened(true)}
              style={{ alignSelf: 'flex-start' }} title={`Its ${n} charts on a new dashboard`}
              data-testid="chat-make-dashboard">
        Make a dashboard from this conversation
      </Button>
      <Modal opened={opened} onClose={() => setOpened(false)} title="New dashboard from this conversation" size="lg"
             data-testid="chat-make-dashboard-modal">
        {opened && <BoardForm turns={turns} conversationId={conversationId} onClose={() => setOpened(false)} />}
      </Modal>
    </>
  )
}

function BoardForm({ turns, conversationId, onClose }: Props & { onClose: () => void }) {
  const { isAdmin, isLoading } = useSession()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [name, setName] = useState(() => defaultBoardName())
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (isLoading) return null
  if (!isAdmin) {
    return (
      <Stack gap="sm" data-testid="chat-make-dashboard-signin">
        <Text size="sm" c="dimmed">Only admins can change the shared dashboards.</Text>
        <SignInButton label="Sign in as admin" variant="button" />
      </Stack>
    )
  }

  const n = turns.length
  async function create() {
    if (!conversationId || !name.trim()) return
    setSaving(true)
    setError(null)
    try {
      const board = await api.post<Dashboard>('/dashboards/from-conversation', { conversation_id: conversationId, name: name.trim() })
      queryClient.invalidateQueries({ queryKey: ['dashboards'] })
      onClose()
      navigate(`/dashboard/${board.id}`)
    } catch (err) {
      setError((err as Error).message || 'The dashboard could not be made.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Stack gap="md">
      <TextInput label="Name" value={name} onChange={e => setName(e.currentTarget.value)} data-testid="chat-make-dashboard-name" />
      <div>
        <Text size="sm" fw={600} mb={4}>Charts</Text>
        <List size="sm" spacing={4}>
          {turns.map(t => (
            <List.Item key={t.key}>
              {defaultTitle(t)} <Text span size="xs" c="dimmed">· {periodChoices(t)[0].label}</Text>
            </List.Item>
          ))}
        </List>
      </div>
      <Text size="xs" c="dimmed">
        Charts whose questions name their dates keep them (<em>yesterday</em> stays yesterday) and are added at once.
        The others follow the dashboard's dates: Claude prepares those. To compare periods on those,
        use <strong>Compare</strong> next to the period.
      </Text>
      {error && <Alert color="red" variant="light" data-testid="chat-make-dashboard-error">{error}</Alert>}
      <Group justify="flex-end">
        <Button variant="default" onClick={onClose} disabled={saving}>Cancel</Button>
        <Button onClick={create} loading={saving} disabled={!name.trim() || !conversationId}
                data-testid="chat-make-dashboard-submit">
          Create dashboard with {n} chart{n === 1 ? '' : 's'}
        </Button>
      </Group>
    </Stack>
  )
}
