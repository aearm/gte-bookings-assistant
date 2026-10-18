// The question box at the bottom of Chat. It keeps its own text, so typing never re-renders the
// conversation. Enter sends, Shift+Enter starts a new line. While an answer streams, Stop ends it.
import { memo, useState } from 'react'
import { ActionIcon, Group, Paper, Text, Textarea, Tooltip } from '@mantine/core'
import { SendIcon, StopIcon } from './icons'

type Props = {
  placeholder: string
  /** An answer is streaming: sending waits, Stop is offered. */
  busy: boolean
  /** Questions can't be answered at all (no data layer, no key...). */
  disabled: boolean
  /** The last answer asks back: what is typed here answers it. */
  answering: boolean
  onSend: (text: string) => void
  onStop: () => void
}

function AskBox({ placeholder, busy, disabled, answering, onSend, onStop }: Props) {
  const [text, setText] = useState('')
  const canSend = !!text.trim() && !busy && !disabled
  const send = () => {
    if (!canSend) return
    onSend(text.trim())
    setText('')
  }
  return (
    <Paper withBorder radius="lg" p={6} shadow="xs" data-testid="chat-askbox">
      {answering && (
        <Text size="xs" c="dimmed" px={8} pt={2} data-testid="chat-answering-hint">
          What you type here answers the question above.
        </Text>
      )}
      <Group gap={6} align="flex-end" wrap="nowrap">
        <Textarea
          variant="unstyled" autosize minRows={1} maxRows={8} px={8} style={{ flex: 1 }}
          placeholder={answering ? 'Type your answer' : placeholder} aria-label="Ask a question"
          value={text} disabled={disabled}
          onChange={e => setText(e.currentTarget.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              send()
            }
          }}
          data-testid="chat-ask"
        />
        {busy ? (
          <Tooltip label="Stop" withArrow>
            <ActionIcon size="lg" radius="xl" variant="light" color="gray" onClick={onStop} aria-label="Stop"
                        data-testid="chat-stop">
              <StopIcon />
            </ActionIcon>
          </Tooltip>
        ) : (
          <ActionIcon size="lg" radius="xl" onClick={send} disabled={!canSend} aria-label="Send"
                      data-testid="chat-send">
            <SendIcon />
          </ActionIcon>
        )}
      </Group>
    </Paper>
  )
}

export default memo(AskBox)
