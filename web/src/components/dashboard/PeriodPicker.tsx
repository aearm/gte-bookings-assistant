// The dashboard's period button: 'This year · 1 Jan – 16 Oct 2026 · W1–42'. It opens the quick choices
// (each with its dates) and a calendar with ISO weeks; a quick choice applies at once, picked days
// apply with Apply. Weeks can also be typed: a year and week numbers.
import { useState } from 'react'
import { Button, Group, NumberInput, Popover, Select } from '@mantine/core'
import { useMediaQuery } from '@mantine/hooks'
import {
  PRESETS, datesText, presetRange, toDay, toIso, weekMonday, weeksInYear, weeksOf, isoWeek,
} from '../../lib/periods'
import { choiceLabel, presetChoice, type PeriodChoice } from '../../lib/periodState'
import { IconCalendar } from '../icons'
import Calendar, { firstMonthShown } from './Calendar'

type Props = { value: PeriodChoice; today: string; onChange: (period: PeriodChoice) => void }

export default function PeriodPicker({ value, today, onChange }: Props) {
  const [opened, setOpened] = useState(false)
  const choose = (period: PeriodChoice) => {
    setOpened(false)
    onChange(period)
  }
  return (
    <Popover opened={opened} onChange={setOpened} position="bottom-start" trapFocus={false} withinPortal>
      <Popover.Target>
        <Button variant="default" leftSection={<IconCalendar size={16} />} onClick={() => setOpened((o) => !o)}
                data-testid="period-button" title="Pick the period: a quick choice, days or weeks on the calendar">
          {choiceLabel(value)}
        </Button>
      </Popover.Target>
      <Popover.Dropdown p="md">
        {opened && <PeriodPanel value={value} today={today} onChoose={choose} />}
      </Popover.Dropdown>
    </Popover>
  )
}

function PeriodPanel({ value, today, onChoose }: { value: PeriodChoice; today: string; onChoose: (p: PeriodChoice) => void }) {
  const wide = useMediaQuery('(min-width: 1000px)', true, { getInitialValueInEffect: false })
  const months = wide ? 2 : 1
  const todayDay = toDay(today)
  const initial: [number, number] = [toDay(value.start), toDay(value.end) - 1]
  const [draft, setDraft] = useState<[number, number]>(initial)
  const [picking, setPicking] = useState(false)
  const [calendarKey, setCalendarKey] = useState(0) // a new key shows the draft's months again
  const [a, b] = draft

  const jumpTo = (first: number, last: number) => {
    setDraft([first, last])
    setCalendarKey((k) => k + 1)
  }
  const apply = () => onChoose({ preset: '', start: toIso(a), end: toIso(b + 1) })

  return (
    <div className="pp" data-testid="period-panel">
      <div className="pp-presets">
        {PRESETS.map((name) => {
          const [s, e] = presetRange(name, todayDay)
          return (
            <button type="button" key={name} className={`pp-preset${value.preset === name ? ' on' : ''}`}
                    onClick={() => onChoose(presetChoice(name, today))} title={datesText(s, e)}>
              {name}<small>{datesText(s, e)}</small>
            </button>
          )
        })}
      </div>
      <div className="pp-main" style={{ width: months === 2 ? 560 : 290 }}>
        <Calendar key={`${calendarKey}-${months}`} range={draft} months={months} today={todayDay}
                  start={firstMonthShown(draft[1], months)} onPicking={setPicking}
                  onRange={(first, last) => setDraft([first, last])} />
        <div className="pp-foot">
          <div className="pp-summary">
            {datesText(a, b + 1)}{' '}
            <span>· {b - a + 1} day{a === b ? '' : 's'} · {weeksOf(a, b + 1)}</span>
          </div>
          <Group gap="xs">
            <Button variant="default" size="xs" onClick={() => jumpTo(...initial)}>Reset</Button>
            <Button size="xs" onClick={apply} disabled={picking} data-testid="period-apply">Apply</Button>
          </Group>
        </div>
        <WeekJump today={todayDay} range={draft} onWeeks={jumpTo} />
        <div className="pp-hint">
          {picking ? 'Now click the last day.'
            : "Click a day and then another for a range · a week number for that week (shift-click to add weeks) · a month's name for the month."}
        </div>
      </div>
    </div>
  )
}

function WeekJump({ today, range, onWeeks }: { today: number; range: [number, number]; onWeeks: (a: number, b: number) => void }) {
  const wa = isoWeek(range[0]), wb = isoWeek(range[1])
  const thisYear = isoWeek(today).year
  const [year, setYear] = useState(String(wb.year))
  const [from, setFrom] = useState<number | string>(wa.year === wb.year ? wa.week : 1)
  const [to, setTo] = useState<number | string>(wb.week)
  const years = Array.from({ length: 12 }, (_, i) => String(thisYear + 1 - i))

  const show = () => {
    const y = Number(year), top = weeksInYear(y)
    const clamp = (w: unknown, fallback: number) => Math.min(Math.max(1, Number(w) || fallback), top)
    let w1 = clamp(from, 1), w2 = clamp(to, w1)
    if (w2 < w1) [w1, w2] = [w2, w1]
    onWeeks(weekMonday(y, w1), weekMonday(y, w2) + 6)
  }

  return (
    <div className="pp-weeks">
      <span>Year</span>
      <Select size="xs" w={84} data={years} value={year} onChange={(v) => v && setYear(v)} allowDeselect={false}
              comboboxProps={{ withinPortal: false }} aria-label="Year" />
      <span>weeks</span>
      <NumberInput size="xs" w={62} min={1} max={53} value={from} onChange={setFrom} aria-label="First week" hideControls />
      <span>to</span>
      <NumberInput size="xs" w={62} min={1} max={53} value={to} onChange={setTo} aria-label="Last week" hideControls />
      <Button size="xs" variant="default" onClick={show}>Show</Button>
    </div>
  )
}
