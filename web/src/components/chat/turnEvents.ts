// How the events of POST /conversations/{id}/ask change a turn. Pure functions, so they can be tested
// by feeding events in (see __tests__/turnEvents.test.ts).
//   step {text} → clarify {question, options} | data {table} → chart {chart} → done {turn}; error {message, details}
import type { Chart, Table, Turn } from '../../api/types'
import type { Sent, TurnView } from './types'

let counter = 0
export function newKey(): string {
  counter += 1
  return `t${Date.now().toString(36)}${counter}`
}

/** A turn that has just been asked: nothing but the question, waiting for the stream. */
export function pendingTurn(sent: Sent, shownAs?: string, key: string = newKey()): TurnView {
  return {
    key, id: '', question: shownAs || sent.question, understanding: '', query: '', cubes: [], explanation: '',
    notes: [], periods: [], table: null, chart: null, clarify: null, error: null, answer_id: null,
    status: 'streaming', steps: [], sent,
  }
}

/** A turn read back from the server (GET /conversations/{id}). */
export function fromServer(turn: Turn): TurnView {
  return {
    ...turn,
    notes: turn.notes ?? [], periods: turn.periods ?? [], cubes: turn.cubes ?? [],
    key: turn.id || newKey(), status: turn.error ? 'error' : 'done', steps: [],
    sent: { question: turn.question },
  }
}

/** The data of the stream's events (each event uses some of these). */
export type EventData = {
  text?: string; question?: string; options?: string[]; table?: Table | null; chart?: Chart | null
  turn?: Partial<Turn>; message?: string; details?: string
}

/** One stream event applied to a turn. Unknown events leave it as it is. */
export function applyEvent(turn: TurnView, event: string, raw: unknown): TurnView {
  const data = (raw ?? {}) as EventData
  switch (event) {
    case 'step':
      return data.text ? { ...turn, steps: [...turn.steps, String(data.text)] } : turn
    case 'clarify':
      return { ...turn, clarify: { question: data.question ?? '', options: data.options ?? [] } }
    case 'data':
      return { ...turn, table: data.table ?? null }
    case 'chart':
      return { ...turn, chart: data.chart ?? null }
    case 'answer': // written answer streamed in pieces (optional)
      return { ...turn, answerText: (turn.answerText ?? '') + (data.text ?? '') }
    case 'done': {
      const full: Partial<Turn> = data.turn ?? {}
      return {
        ...turn,
        ...full,
        // the question as shown here ("question → answer" after a clarification)
        question: turn.question || full.question || '',
        table: full.table ?? turn.table,
        chart: full.chart ?? turn.chart,
        clarify: full.clarify ?? turn.clarify,
        notes: full.notes ?? turn.notes,
        periods: full.periods ?? turn.periods,
        cubes: full.cubes ?? turn.cubes,
        status: full.error ? 'error' : 'done',
      }
    }
    case 'error':
      return { ...turn, status: 'error', error: data.message || 'Something went wrong.', details: data.details || undefined }
    default:
      return turn
  }
}

/** The stream has ended (or was stopped): a turn still marked as streaming gets its final state. */
export function finishStream(turn: TurnView, stopped: boolean): TurnView {
  if (turn.status !== 'streaming') return turn
  if (stopped) return { ...turn, status: 'stopped' }
  if (turn.clarify) return { ...turn, status: 'done' }
  return { ...turn, status: 'error', error: 'The answer stopped before it was ready. Please ask again.' }
}

/** A failure before or during the stream (network, server refused the request). */
export function failTurn(turn: TurnView, message: string, details?: string): TurnView {
  return applyEvent(turn, 'error', { message, details })
}

/** The last turn's clarifying question, if it is still waiting for an answer. */
export function openQuestion(turns: TurnView[]): TurnView | null {
  const last = turns[turns.length - 1]
  return last && last.clarify && !last.answered && last.status === 'done' ? last : null
}

/** Answers with a chart or table that can go on a dashboard (views/chat.py chart_turns). */
export function chartTurns(turns: TurnView[]): TurnView[] {
  return turns.filter(t => t.status === 'done' && t.id && t.query && t.table && t.table.rows.length > 0)
}
