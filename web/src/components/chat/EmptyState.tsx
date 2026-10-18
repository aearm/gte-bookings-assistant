// Before the first question: example questions and the questions asked recently, one click to ask.
import { memo } from 'react'
import { Anchor, Button, SimpleGrid, Stack, Title } from '@mantine/core'
import type { HistoryItem } from './types'

type Props = { examples: string[]; history: HistoryItem[]; disabled: boolean; onPick: (question: string) => void }

const short = (text: string, n = 60) => (text.length > n ? `${text.slice(0, n - 1)}…` : text)

function EmptyState({ examples, history, disabled, onPick }: Props) {
  const recent = [...new Set(history.map(h => h.question).filter(Boolean))].slice(0, 8)
  if (!examples.length && !recent.length) return null
  const wrap = { label: { whiteSpace: 'normal' as const, textAlign: 'left' as const }, inner: { justifyContent: 'flex-start' },
    root: { height: 'auto', minHeight: 40, paddingBlock: 8 } }
  return (
    <Stack gap="lg" data-testid="chat-empty">
      {examples.length > 0 && (
        <Stack gap="xs">
          <Title order={5}>Try asking</Title>
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs" data-testid="chat-examples">
            {examples.slice(0, 6).map(q => (
              <Button key={q} variant="default" disabled={disabled} onClick={() => onPick(q)} styles={wrap}
                      data-testid="chat-example">
                {q}
              </Button>
            ))}
          </SimpleGrid>
        </Stack>
      )}
      {recent.length > 0 && (
        <Stack gap={4} data-testid="chat-recent">
          <Title order={5}>Recent questions</Title>
          {recent.map(q => (
            <Anchor key={q} component="button" type="button" size="sm" ta="left" title={q} disabled={disabled}
                    onClick={() => onPick(q)} data-testid="chat-recent-question" style={{ alignSelf: 'flex-start' }}>
              {short(q)}
            </Anchor>
          ))}
        </Stack>
      )}
    </Stack>
  )
}

export default memo(EmptyState)
