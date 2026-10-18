// Claude asks back: the question, its suggested answers as buttons, and a box for an answer of your own.
// (Text typed in the ask box at the bottom also answers it.)
import { memo, useState } from 'react'
import { Button, Group, SimpleGrid, Stack, Text, TextInput } from '@mantine/core'
import { SendIcon } from './icons'

type Props = {
  question: string
  options: string[]
  answered: boolean
  /** Another answer is on its way: the buttons wait. */
  busy: boolean
  onAnswer: (answer: string) => void
}

function ClarifyBlock({ question, options, answered, busy, onAnswer }: Props) {
  const [own, setOwn] = useState('')
  const disabled = answered || busy
  const send = () => {
    if (!own.trim() || disabled) return
    onAnswer(own.trim())
    setOwn('')
  }
  return (
    <Stack gap="xs" data-testid="chat-clarify">
      <Text fw={600} data-testid="chat-clarify-question">{question}</Text>
      {options.length > 0 && (
        <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="xs">
          {options.map(option => (
            <Button key={option} variant="default" disabled={disabled} onClick={() => onAnswer(option)}
                    styles={{ label: { whiteSpace: 'normal', textAlign: 'center' }, root: { height: 'auto', minHeight: 36, paddingBlock: 6 } }}
                    data-testid="chat-clarify-option">
              {option}
            </Button>
          ))}
        </SimpleGrid>
      )}
      {!answered && (
        <Group gap="xs" align="flex-end" wrap="nowrap">
          <TextInput style={{ flex: 1 }} placeholder="Or type your own answer" value={own} disabled={busy}
                     onChange={e => setOwn(e.currentTarget.value)}
                     onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); send() } }}
                     data-testid="chat-clarify-input" aria-label="Your answer" />
          <Button onClick={send} disabled={!own.trim() || busy} leftSection={<SendIcon />}
                  data-testid="chat-clarify-send">
            Answer
          </Button>
        </Group>
      )}
      {!answered && <Text size="xs" c="dimmed">Pick an answer, or type your own below.</Text>}
    </Stack>
  )
}

export default memo(ClarifyBlock)
