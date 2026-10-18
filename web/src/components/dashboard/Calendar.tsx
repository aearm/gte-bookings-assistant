// A calendar for picking days, with ISO week numbers: click a day and then another for a range;
// click a week number for that week (shift-click another to extend); click a month's name for the
// whole month. Days are day numbers (lib/periods); the range is inclusive [first, last].
import { useState } from 'react'
import { MONTHS, fromYmd, isoWeek, weekday, ymd } from '../../lib/periods'
import { IconChevronLeft, IconChevronRight } from '../icons'

export type CalendarProps = {
  range: [number, number] // first and last day, both included
  onRange: (first: number, last: number) => void
  today: number
  months?: 1 | 2
  /** the month shown first (year, month 1-12); by default the month before the last day's (two months) */
  start?: [number, number]
  onPicking?: (picking: boolean) => void // true after the first click of a range
}

const DOW = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
const step = ([y, m]: [number, number], by: number): [number, number] => {
  const [ny, nm] = ymd(fromYmd(y, m + by, 1))
  return [ny, nm]
}

export function firstMonthShown(lastDay: number, months: 1 | 2): [number, number] {
  const [y, m] = ymd(lastDay)
  return months === 2 ? step([y, m], -1) : [y, m]
}

export default function Calendar({ range, onRange, today, months = 2, start, onPicking }: CalendarProps) {
  const [view, setView] = useState<[number, number]>(() => start ?? firstMonthShown(range[1], months))
  const [anchor, setAnchor] = useState<number | null>(null)
  const [hover, setHover] = useState<number | null>(null)
  const [lastWeek, setLastWeek] = useState<number | null>(null)

  const [a, b] = anchor !== null && hover !== null ? [Math.min(anchor, hover), Math.max(anchor, hover)] : range

  const pickDay = (day: number) => {
    if (anchor === null) {
      setAnchor(day)
      setHover(day)
      onPicking?.(true)
      onRange(day, day)
    } else {
      onRange(Math.min(anchor, day), Math.max(anchor, day))
      setAnchor(null)
      setHover(null)
      onPicking?.(false)
    }
  }
  const pickWeek = (monday: number, extend: boolean) => {
    setAnchor(null)
    onPicking?.(false)
    if (extend && lastWeek !== null) onRange(Math.min(lastWeek, monday), Math.max(lastWeek, monday) + 6)
    else {
      setLastWeek(monday)
      onRange(monday, monday + 6)
    }
  }
  const pickMonth = (y: number, m: number) => {
    setAnchor(null)
    onPicking?.(false)
    onRange(fromYmd(y, m, 1), fromYmd(y, m + 1, 1) - 1)
  }

  const shown = Array.from({ length: months }, (_, i) => step(view, i))
  return (
    <div className="pp-months">
      {shown.map(([y, m], i) => (
        <div className="pp-month" key={`${y}-${m}`}>
          <div className="pp-head">
            <button type="button" className={`pp-nav${i === 0 ? '' : ' hidden'}`} title="Earlier month"
                    onClick={() => setView((v) => step(v, -1))}><IconChevronLeft size={16} /></button>
            <button type="button" className="title" title="Pick the whole month" onClick={() => pickMonth(y, m)}>
              {MONTHS[m - 1]} {y}
            </button>
            <button type="button" className={`pp-nav${i === months - 1 ? '' : ' hidden'}`} title="Later month"
                    onClick={() => setView((v) => step(v, 1))}><IconChevronRight size={16} /></button>
          </div>
          <MonthGrid year={y} month={m} first={a} last={b} today={today} onDay={pickDay} onWeek={pickWeek}
                     onHover={anchor !== null ? setHover : undefined} />
        </div>
      ))}
    </div>
  )
}

type GridProps = {
  year: number; month: number; first: number; last: number; today: number
  onDay: (day: number) => void
  onWeek: (monday: number, extend: boolean) => void
  onHover?: (day: number) => void
}

function MonthGrid({ year, month, first, last, today, onDay, onWeek, onHover }: GridProps) {
  const start = fromYmd(year, month, 1), end = fromYmd(year, month + 1, 1) - 1
  const weeks: number[] = []
  for (let monday = start - weekday(start); monday <= end; monday += 7) weeks.push(monday)
  return (
    <div className="pp-grid" role="grid" aria-label={`${MONTHS[month - 1]} ${year}`}>
      <div className="wkh">Wk</div>
      {DOW.map((d) => <div className="dow" key={d}>{d}</div>)}
      {weeks.map((monday) => {
        const w = isoWeek(monday)
        return [
          <button type="button" key={`w${monday}`} className="wk" data-week={w.week}
                  title={`Week ${w.week} of ${w.year} — shift-click another week to pick several`}
                  onClick={(e) => onWeek(monday, e.shiftKey)}>{w.week}</button>,
          ...Array.from({ length: 7 }, (_, k) => {
            const day = monday + k
            const cls = ['d']
            if (day < start || day > end) cls.push('out')
            if (day >= first && day <= last) cls.push(day === first || day === last ? 'edge' : 'in')
            if (day === first || k === 0) cls.push('first')
            if (day === last || k === 6) cls.push('last')
            if (day === today) cls.push('today')
            return (
              <button type="button" key={day} className={cls.join(' ')} data-day={day}
                      onClick={() => onDay(day)} onMouseEnter={onHover ? () => onHover(day) : undefined}>
                {ymd(day)[2]}
              </button>
            )
          }),
        ]
      })}
    </div>
  )
}
