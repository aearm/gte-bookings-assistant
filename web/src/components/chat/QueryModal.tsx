// "Show the query": how Claude got the numbers (its explanation and the plan's query text).
import { Code, CopyButton, Button, Group, Modal, ScrollArea, Stack, Text } from '@mantine/core'
import type { TurnView } from './types'

export default function QueryModal({ turn, onClose }: { turn: TurnView | null; onClose: () => void }) {
  const cubes = turn?.cubes.length ?? 0
  return (
    <Modal opened={!!turn} onClose={onClose} size="xl" data-testid="chat-query-modal"
           title={`The query${cubes > 1 ? ` (${cubes} cubes, joined)` : ''}`}>
      {turn && (
        <Stack gap="sm">
          {turn.explanation && <Text size="sm" c="dimmed" data-testid="chat-query-explanation">{turn.explanation}</Text>}
          <ScrollArea.Autosize mah="60vh">
            <Code block data-testid="chat-query-text" style={{ whiteSpace: 'pre' }}>{turn.query}</Code>
          </ScrollArea.Autosize>
          <Group justify="flex-end">
            <CopyButton value={turn.query}>
              {({ copied, copy }) => (
                <Button variant="default" size="xs" onClick={copy}>{copied ? 'Copied' : 'Copy the query'}</Button>
              )}
            </CopyButton>
          </Group>
        </Stack>
      )}
    </Modal>
  )
}
