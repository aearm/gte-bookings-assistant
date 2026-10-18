// "Change the chart": the same numbers drawn the way you describe (no new query). The modal closes at
// once; the chart shows that it is being redrawn while you can go on asking.
import { useState } from 'react'
import { Button, Group, Modal, Stack, Text, Textarea } from '@mantine/core'
import type { TurnView } from './types'

type Props = { turn: TurnView | null; onClose: () => void; onDraw: (key: string, request: string) => void }

export default function ChangeChartModal({ turn, onClose, onDraw }: Props) {
  return (
    <Modal opened={!!turn} onClose={onClose} title="Change the chart" size="lg" data-testid="chat-chart-modal">
      {turn && <ChartForm key={turn.key} turn={turn} onClose={onClose} onDraw={onDraw} />}
    </Modal>
  )
}

function ChartForm({ turn, onClose, onDraw }: { turn: TurnView; onClose: () => void; onDraw: Props['onDraw'] }) {
  const [request, setRequest] = useState('')
  const draw = () => {
    if (!request.trim()) return
    onDraw(turn.key, request.trim())
    onClose()
  }
  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">Same numbers, drawn the way you describe.</Text>
      <Textarea label="Describe the chart" autosize minRows={3} maxRows={8} autoFocus value={request}
                onChange={e => setRequest(e.currentTarget.value)} data-testid="chat-chart-request"
                placeholder="e.g. bars for sales by month with a line for profit % on a second axis"
                description="Any chart: combos, two axes, stacked percentages, funnels, sunbursts, waterfalls... Claude draws it from the chart's data."
                onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); draw() } }} />
      <Group justify="flex-end">
        <Button variant="default" onClick={onClose}>Cancel</Button>
        <Button onClick={draw} disabled={!request.trim()} data-testid="chat-chart-draw">Draw it</Button>
      </Group>
    </Stack>
  )
}
