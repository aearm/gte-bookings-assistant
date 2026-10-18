// Chat with the data (views/chat.py): ask about all the data (Claude picks the cubes, and joins them
// when a question needs several) or one cube; see how Claude understood the question, answer its
// clarifying questions, and get the data, a chart and a short answer as they are ready (streamed).
// Change any chart in words, add it to a dashboard, or make a dashboard from the whole conversation.
// The conversation lives in a store (components/chat/chatStore.ts): it is still there after visiting
// another page (an answer on its way keeps arriving meanwhile), and after a reload it is read back from
// the server, with a question still being answered followed until its answer is there.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Anchor, Box, Button, Group, Loader, Select, Stack, Text, Title, useComputedColorScheme } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { api } from '../api/client'
import type { Info } from '../api/types'
import { useSession } from '../components/auth/useSession'
import AddToDashboardModal from '../components/chat/AddToDashboardModal'
import AskBox from '../components/chat/AskBox'
import ChangeChartModal from '../components/chat/ChangeChartModal'
import { useChatStore } from '../components/chat/chatStore'
import DashboardFromConversation from '../components/chat/DashboardFromConversation'
import EmptyState from '../components/chat/EmptyState'
import { InfoIcon, PlusIcon } from '../components/chat/icons'
import QueryModal from '../components/chat/QueryModal'
import TurnCard, { type TurnAction } from '../components/chat/TurnCard'
import { chartTurns, openQuestion } from '../components/chat/turnEvents'
import type { Conversation, HistoryItem } from '../components/chat/types'

const ALL = '__all__' // the picker's value for "All data" (scope "")
const EMPTY: Conversation = { id: null, turns: [] }

export default function ChatPage() {
  const queryClient = useQueryClient()
  const { isAdmin } = useSession()
  const dark = useComputedColorScheme('light') === 'dark'
  const info = useQuery<Info>({ queryKey: ['info'], queryFn: () => api.get<Info>('/info') })
  const history = useQuery<HistoryItem[]>({ queryKey: ['history'], queryFn: () => api.get<HistoryItem[]>('/history') })

  // the "Data" picked: kept in the store (and the session); the first scope until one is picked
  const storeScope = useChatStore(s => s.scope)
  const setScope = useChatStore(s => s.setScope)
  const scopes = useMemo(() => info.data?.scopes ?? [], [info.data])
  const scope = storeScope !== null && scopes.some(s => s.value === storeScope) ? storeScope : (scopes[0]?.value ?? null)
  useEffect(() => { if (scope !== null && scope !== storeScope) setScope(scope) }, [scope, storeScope, setScope])

  const conversation = useChatStore(s => (scope === null ? undefined : s.conversations[scope])) ?? EMPTY
  const { ask, reply, retry, newChat, restore, redraw, verify, stop } = useChatStore.getState()
  const turns = conversation.turns
  const busy = turns.some(t => t.status === 'streaming')
  const answering = !!openQuestion(turns)

  // after a reload: this scope's conversation back from the server
  useEffect(() => { if (scope !== null) void restore(scope) }, [scope, restore])

  // a finished answer is in the recent questions now
  const finished = turns.reduce((n, t) => n + (t.status === 'done' ? 1 : 0), 0)
  useEffect(() => { if (finished) void queryClient.invalidateQueries({ queryKey: ['history'] }) }, [finished, queryClient])

  // a new question scrolls into view
  const endRef = useRef<HTMLDivElement>(null)
  const count = useRef(turns.length)
  useEffect(() => {
    if (turns.length > count.current) endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    count.current = turns.length
  }, [turns.length])

  const cubeLabels = useMemo(() => Object.fromEntries(scopes.filter(s => s.value).map(s => [s.value, s.label])), [scopes])
  const scopeName = scope ? (cubeLabels[scope] ?? scope) : 'all the data'
  const ready = info.data?.ready !== false

  const [dialog, setDialog] = useState<{ action: TurnAction; key: string } | null>(null)
  const dialogTurn = dialog ? turns.find(t => t.key === dialog.key) ?? null : null
  const closeDialog = useCallback(() => setDialog(null), [])

  const onSend = useCallback((text: string) => { if (scope !== null) void ask(scope, text) }, [scope, ask])
  const onAnswer = useCallback((answer: string) => { if (scope !== null) void reply(scope, answer) }, [scope, reply])
  const onRetry = useCallback((key: string) => { if (scope !== null) void retry(scope, key) }, [scope, retry])
  const onStop = useCallback(() => { if (scope !== null) stop(scope) }, [scope, stop])
  const onAction = useCallback((action: TurnAction, key: string) => setDialog({ action, key }), [])
  const onDraw = useCallback((key: string, request: string) => { if (scope !== null) void redraw(scope, key, request) }, [scope, redraw])
  const onVerify = useCallback((key: string) => {
    if (scope === null) return
    verify(scope, key).catch((err: Error) => notifications.show({
      color: 'red', title: 'Could not mark it as correct', message: err.message,
    }))
  }, [scope, verify])

  const withCharts = useMemo(() => chartTurns(turns), [turns])

  if (info.isLoading) {
    return <Group p="xl" justify="center" data-testid="ChatPage"><Loader size="sm" /></Group>
  }
  if (info.isError || !info.data) {
    return (
      <Stack p="md" data-testid="ChatPage">
        <Title order={2}>Chat</Title>
        <Alert color="red" variant="light">The app's server can't be reached right now. Try again in a moment.</Alert>
      </Stack>
    )
  }
  if (!scopes.length || scope === null) {
    return (
      <Stack p="md" data-testid="ChatPage">
        <Title order={2}>Chat</Title>
        <Alert variant="light" icon={<InfoIcon />}>
          No cube is connected yet. An admin connects cubes on the <Anchor component={Link} to="/cubes">Cubes page</Anchor>.
        </Alert>
      </Stack>
    )
  }

  return (
    <Stack gap="md" maw={1100} mx="auto" w="100%" data-testid="ChatPage"
           style={{ minHeight: 'calc(100dvh - var(--app-shell-header-offset, 0px) - 2rem)' }}>
      <Group justify="space-between" align="flex-end" wrap="wrap" gap="sm">
        <Title order={2}>Chat</Title>
        <Group gap="sm" align="flex-end">
          <Select label="Data" w={260} allowDeselect={false} data-testid="chat-scope"
                  data={scopes.map(s => ({ value: s.value || ALL, label: s.label }))}
                  value={scope || ALL} onChange={v => v && setScope(v === ALL ? '' : v)} />
          <Button variant="default" leftSection={<PlusIcon />} onClick={() => newChat(scope)}
                  disabled={!turns.length && !conversation.id} data-testid="chat-new">
            New chat
          </Button>
        </Group>
      </Group>
      <Text size="sm" c="dimmed">
        Ask about <strong>{scopeName}</strong> in plain English. Claude checks the data first, tells you how it
        understood the question, asks if something is unclear, and combines cubes when a question needs several.
        Ask for any chart you like. Add any chart to a dashboard, or make a dashboard from the whole conversation.
      </Text>

      {!ready && (
        <Alert variant="light" color="yellow" icon={<InfoIcon />} data-testid="chat-not-ready">
          {info.data.why || "Questions can't be answered yet."}{' '}
          {/settings/i.test(info.data.why) && <Anchor component={Link} to="/settings">Open the Settings page</Anchor>}
          {/cube/i.test(info.data.why) && <Anchor component={Link} to="/cubes">Open the Cubes page</Anchor>}
        </Alert>
      )}

      <Stack gap="xl" style={{ flex: 1 }} data-testid="chat-turns">
        {conversation.loading && (
          <Group gap="xs" c="dimmed"><Loader size="xs" /><Text size="sm">Loading the conversation…</Text></Group>
        )}
        {!turns.length && !conversation.loading && (
          <EmptyState examples={info.data.example_questions ?? []} history={history.data ?? []}
                      disabled={!ready || busy} onPick={onSend} />
        )}
        {turns.map((turn, i) => (
          <TurnCard key={turn.key} turn={turn} conversationId={conversation.id} isAdmin={isAdmin} dark={dark}
                    isLast={i === turns.length - 1} busy={i === turns.length - 1 && busy} cubeLabels={cubeLabels}
                    onAction={onAction} onAnswer={onAnswer} onRetry={onRetry} onVerify={onVerify} />
        ))}
        {withCharts.length >= 2 && <DashboardFromConversation turns={withCharts} conversationId={conversation.id} />}
        <div ref={endRef} />
      </Stack>

      <Box pos="sticky" bottom={0} pt="xs" pb="md" style={{ zIndex: 10, background: 'var(--mantine-color-body)' }}>
        <AskBox placeholder={`Ask a question about ${scopeName}`} busy={busy} disabled={!ready}
                answering={answering} onSend={onSend} onStop={onStop} />
      </Box>

      <AddToDashboardModal turn={dialog?.action === 'add' ? dialogTurn : null} conversationId={conversation.id}
                           onClose={closeDialog} />
      <ChangeChartModal turn={dialog?.action === 'chart' ? dialogTurn : null} onClose={closeDialog} onDraw={onDraw} />
      <QueryModal turn={dialog?.action === 'query' ? dialogTurn : null} onClose={closeDialog} />
    </Stack>
  )
}
