// The "Compare" button next to the period: no comparison, the previous period, the same period last
// year or other dates, each with the dates it means for the period picked. One choice for the whole
// dashboard; charts that can show it do (the period in colour, the comparison in grey).
import { useState } from 'react'
import { Button, Group, Popover, Radio, Stack, Text } from '@mantine/core'
import { COMPARE_MODES, datesText, toDay, toIso, type CompareMode } from '../../lib/periods'
import {
  COMPARE_ORDER, compareButtonLabel, compareDates, customRange, type CompareChoice, type PeriodChoice,
} from '../../lib/periodState'
import { IconCompare } from '../icons'
import Calendar from './Calendar'

type Props = { period: PeriodChoice; value: CompareChoice; today: string; onChange: (compare: CompareChoice) => void }

export default function ComparePicker({ period, value, today, onChange }: Props) {
  const [opened, setOpened] = useState(false)
  return (
    <Popover opened={opened} onChange={setOpened} position="bottom-start" trapFocus={false} withinPortal>
      <Popover.Target>
        <Button variant="default" leftSection={<IconCompare size={16} />} onClick={() => setOpened((o) => !o)}
                data-testid="compare-button" title="Compare every chart with another period: this period in colour, the other in grey">
          {compareButtonLabel(period, value)}
        </Button>
      </Popover.Target>
      <Popover.Dropdown p="md" maw={420}>
        {opened && <ComparePanel period={period} value={value} today={today}
                                 onChoose={(c, close) => { onChange(c); if (close) setOpened(false) }} />}
      </Popover.Dropdown>
    </Popover>
  )
}

function ComparePanel({ period, value, today, onChoose }: {
  period: PeriodChoice; value: CompareChoice; today: string; onChoose: (c: CompareChoice, close: boolean) => void
}) {
  const [mode, setMode] = useState<CompareMode>(value.mode)
  // other dates: the ones picked before, else the previous period to start from
  const fallback = customRange(value) ?? compareDates('previous', period, null)!
  const [draft, setDraft] = useState<[number, number]>([fallback[0], fallback[1] - 1])
  const [picking, setPicking] = useState(false)

  const pick = (next: string) => {
    const m = next as CompareMode
    setMode(m)
    if (m !== 'custom') onChoose({ mode: m, start: '', end: '' }, true)
  }

  return (
    <Stack gap="sm" data-testid="compare-panel">
      <Radio.Group label="Compare with" value={mode} onChange={pick}>
        <Stack gap={8} mt={6}>
          {COMPARE_ORDER.map((m) => {
            const dates = compareDates(m, period, m === 'custom' ? [draft[0], draft[1] + 1] : null)
            return (
              <Radio key={m} value={m} className="cmp-option"
                     label={<>{COMPARE_MODES[m]}<small>{dates ? datesText(...dates) : 'Show this period only'}</small></>} />
            )
          })}
        </Stack>
      </Radio.Group>
      {mode === 'custom' && (
        <>
          <Calendar range={draft} months={1} today={toDay(today)} onPicking={setPicking}
                    onRange={(a, b) => setDraft([a, b])} />
          <Group justify="space-between">
            <Text size="xs" c="dimmed">{picking ? 'Now click the last day.' : 'Click the first day, then the last.'}</Text>
            <Button size="xs" disabled={picking} data-testid="compare-apply"
                    onClick={() => onChoose({ mode: 'custom', start: toIso(draft[0]), end: toIso(draft[1] + 1) }, true)}>
              Apply
            </Button>
          </Group>
        </>
      )}
      <Text size="xs" c="dimmed">
        Shown on headline numbers, columns, bars, lines and tables of one measure: this period in colour, the other in
        grey, with the change. Maps, donuts and charts of several measures show this period only.
      </Text>
    </Stack>
  )
}
