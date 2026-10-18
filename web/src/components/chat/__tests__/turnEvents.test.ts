// The /ask stream's events applied to a turn, as the Chat page does while an answer streams.
import { describe, expect, it } from 'vitest'
import type { Chart, Table, Turn } from '../../../api/types'
import { applyEvent, chartTurns, finishStream, fromServer, openQuestion, pendingTurn } from '../turnEvents'
import type { TurnView } from '../types'

const table: Table = {
  columns: [{ name: 'Month', type: 'text' }, { name: 'Bookings', type: 'number' }],
  rows: [['Jan', 10], ['Feb', 12]], row_count: 2, truncated: false,
}
const chart: Chart = { kind: 'bar', option: { series: [] }, title: 'Bookings by month', summary: '**22** bookings.', note: '' }
const full: Turn = {
  id: 'turn1', question: 'Bookings by month', understanding: 'Number of bookings per month this year',
  query: 'EVALUATE ...', cubes: ['Bookings'], explanation: 'Counts bookings', notes: ['Cancelled ones excluded'],
  periods: [{ phrase: 'this year', start: '2026-01-01', end: '2026-10-17' }], table, chart, clarify: null,
  error: null, answer_id: 7,
}

const feed = (turn: TurnView, events: [string, unknown][]) => events.reduce((t, [e, d]) => applyEvent(t, e, d), turn)

describe('applyEvent', () => {
  it('streams steps, then the data, the chart and the full turn', () => {
    let t = pendingTurn({ question: 'Bookings by month' })
    expect(t.status).toBe('streaming')
    t = feed(t, [['step', { text: 'Understanding the question' }], ['step', { text: 'Pulling the data' }]])
    expect(t.steps).toEqual(['Understanding the question', 'Pulling the data'])
    expect(t.table).toBeNull()

    t = applyEvent(t, 'data', { table })
    expect(t.table).toBe(table)
    expect(t.chart).toBeNull()
    expect(t.status).toBe('streaming')

    t = applyEvent(t, 'chart', { chart })
    expect(t.chart).toBe(chart)

    const key = t.key
    t = applyEvent(t, 'done', { turn: full })
    expect(t.status).toBe('done')
    expect(t.id).toBe('turn1')
    expect(t.key).toBe(key) // the page's key stays, so the card isn't remounted
    expect(t.understanding).toBe('Number of bookings per month this year')
    expect(t.answer_id).toBe(7)
    expect(t.steps).toHaveLength(2) // progress lines are kept for the collapsed panel
  })

  it('keeps the question as shown after a clarification', () => {
    const t0 = pendingTurn({ question: 'Compare errors', clarification: { question: 'Which errors?', answer: 'Booking errors' } },
      'Compare errors → Booking errors')
    const t = applyEvent(t0, 'done', { turn: { ...full, question: 'Compare errors' } })
    expect(t.question).toBe('Compare errors → Booking errors')
    expect(t.sent.clarification?.answer).toBe('Booking errors')
  })

  it('keeps the streamed table and chart when done leaves them out', () => {
    const t = feed(pendingTurn({ question: 'q' }), [['data', { table }], ['chart', { chart }],
      ['done', { turn: { ...full, table: null, chart: null } }]])
    expect(t.table).toBe(table)
    expect(t.chart).toBe(chart)
  })

  it('shows a clarifying question', () => {
    const t = feed(pendingTurn({ question: 'Compare errors this week with last week' }), [
      ['step', { text: 'Understanding the question' }],
      ['clarify', { question: 'Which errors do you mean?', options: ['Booking errors', 'Payment errors'] }],
      ['done', { turn: { ...full, table: null, chart: null, clarify: { question: 'Which errors do you mean?', options: ['Booking errors', 'Payment errors'] } } }],
    ])
    expect(t.status).toBe('done')
    expect(t.clarify?.options).toEqual(['Booking errors', 'Payment errors'])
    expect(openQuestion([t])).toBe(t)
    expect(openQuestion([{ ...t, answered: true }])).toBeNull()
  })

  it('turns an error event into an error turn with details', () => {
    const t = feed(pendingTurn({ question: 'q' }), [['step', { text: 'Pulling the data' }],
      ['error', { message: "The cube server didn't answer.", details: 'Timeout after 60 s' }]])
    expect(t.status).toBe('error')
    expect(t.error).toBe("The cube server didn't answer.")
    expect(t.details).toBe('Timeout after 60 s')
  })

  it('marks a done turn that carries an error as failed', () => {
    const t = applyEvent(pendingTurn({ question: 'q' }), 'done', { turn: { ...full, error: 'No data for that period.' } })
    expect(t.status).toBe('error')
  })

  it('adds up streamed answer text and ignores unknown events', () => {
    const t0 = pendingTurn({ question: 'q' })
    const t = feed(t0, [['answer', { text: 'Sales rose ' }], ['answer', { text: 'by 4%.' }]])
    expect(t.answerText).toBe('Sales rose by 4%.')
    expect(applyEvent(t0, 'ping', {})).toBe(t0)
    expect(applyEvent(t0, 'step', {})).toBe(t0)
  })
})

describe('finishStream', () => {
  it('a stream that ends without done is an error, a stopped one is stopped', () => {
    const t = applyEvent(pendingTurn({ question: 'q' }), 'data', { table })
    expect(finishStream(t, false).status).toBe('error')
    expect(finishStream(t, true).status).toBe('stopped')
    const asked = applyEvent(pendingTurn({ question: 'q' }), 'clarify', { question: 'Which?', options: [] })
    expect(finishStream(asked, false).status).toBe('done')
  })

  it('leaves finished turns alone', () => {
    const t = applyEvent(pendingTurn({ question: 'q' }), 'done', { turn: full })
    expect(finishStream(t, true)).toBe(t)
  })
})

describe('turns read back and turns with charts', () => {
  it('reads server turns as finished ones', () => {
    const t = fromServer(full)
    expect(t.status).toBe('done')
    expect(t.key).toBe('turn1')
    expect(t.sent.question).toBe('Bookings by month')
    expect(fromServer({ ...full, error: 'Failed' }).status).toBe('error')
  })

  it('only answers with rows can go on a dashboard', () => {
    const withRows = fromServer(full)
    const empty = fromServer({ ...full, id: 't2', table: { ...table, rows: [], row_count: 0 } })
    const asked = fromServer({ ...full, id: 't3', query: '', table: null, chart: null, clarify: { question: 'Which?', options: [] } })
    expect(chartTurns([withRows, empty, asked])).toEqual([withRows])
  })
})
