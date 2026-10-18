// The Chat store with the server faked: events fed through stream() end up in the conversation.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Chart, Table, Turn } from '../../../api/types'

type OnEvent = (event: string, data: unknown) => void
type Script = (onEvent: OnEvent, signal?: AbortSignal) => Promise<void>

const server = vi.hoisted(() => ({
  scripts: [] as Script[],
  calls: [] as { path: string; body: unknown }[],
  posts: [] as { path: string; body: unknown }[],
  gets: {} as Record<string, unknown>, // a reply, or a function giving the next one
  nextId: 1,
}))

vi.mock('../../../api/client', () => {
  class ApiError extends Error {
    status: number
    details?: string
    constructor(status: number, message: string, details?: string) {
      super(message)
      this.status = status
      this.details = details
    }
  }
  return {
    ApiError,
    api: {
      post: vi.fn(async (path: string, body: unknown) => {
        server.posts.push({ path, body })
        if (path === '/conversations') return { id: `c${server.nextId++}` }
        if (path.endsWith('/chart')) {
          return { chart: { kind: 'line', option: { series: [{ type: 'line' }] }, title: 'Bookings by month', summary: 'new text', note: '' } }
        }
        return { ok: true }
      }),
      get: vi.fn(async (path: string) => {
        if (path in server.gets) {
          const reply = server.gets[path]
          return typeof reply === 'function' ? reply() : reply
        }
        throw new ApiError(404, 'Not found')
      }),
    },
    stream: vi.fn(async (path: string, body: unknown, onEvent: OnEvent, signal?: AbortSignal) => {
      server.calls.push({ path, body })
      const script = server.scripts.shift()
      if (script) await script(onEvent, signal)
    }),
  }
})

const { useChatStore, resetChatStore, FOLLOW_EVERY_MS } = await import('../chatStore')
const { ApiError } = await import('../../../api/client')

const table: Table = { columns: [{ name: 'Month', type: 'text' }, { name: 'Bookings', type: 'number' }], rows: [['Jan', 3]], row_count: 1, truncated: false }
const chart: Chart = { kind: 'bar', option: { series: [{ type: 'bar' }] }, title: 'Bookings by month', summary: 'Bookings grew.', note: '' }
const turn = (over: Partial<Turn> = {}): Turn => ({
  id: 't1', question: 'Bookings by month', understanding: 'Bookings per month', query: 'EVALUATE ...', cubes: ['Bookings'],
  explanation: '', notes: [], periods: [], table, chart, clarify: null, error: null, answer_id: 5, ...over,
})
const answerScript = (over: Partial<Turn> = {}): Script => async onEvent => {
  onEvent('step', { text: 'Understanding the question' })
  onEvent('data', { table })
  onEvent('chart', { chart })
  onEvent('done', { turn: turn(over) })
}

function fakeStorage() {
  const data = new Map<string, string>()
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
    clear: () => data.clear(),
  }
}

const conv = (scope = '') => useChatStore.getState().conversations[scope]

beforeEach(() => {
  vi.stubGlobal('sessionStorage', fakeStorage())
  server.scripts = []
  server.calls = []
  server.posts = []
  server.gets = {}
  server.nextId = 1
  resetChatStore()
})
afterEach(() => vi.unstubAllGlobals())

describe('asking', () => {
  it('creates the conversation, streams the answer into a turn and remembers the id for a reload', async () => {
    server.scripts.push(answerScript())
    await useChatStore.getState().ask('', '  Bookings by month ')
    expect(server.posts[0]).toEqual({ path: '/conversations', body: { scope: '' } })
    expect(server.calls[0]).toEqual({ path: '/conversations/c1/ask', body: { question: 'Bookings by month' } })
    const c = conv()
    expect(c.id).toBe('c1')
    expect(c.turns).toHaveLength(1)
    expect(c.turns[0]).toMatchObject({ status: 'done', id: 't1', steps: ['Understanding the question'], table, chart })
    expect(JSON.parse(sessionStorage.getItem('chat.conversations')!)).toEqual({ '': 'c1' })
  })

  it('shows each event as it arrives', async () => {
    const seen: string[] = []
    server.scripts.push(async onEvent => {
      onEvent('step', { text: 'Picking the cubes that answer it' })
      seen.push(conv().turns[0].steps.join('|'))
      onEvent('data', { table })
      seen.push(conv().turns[0].table ? 'table' : 'no table')
      onEvent('done', { turn: turn() })
    })
    await useChatStore.getState().ask('', 'Bookings by month')
    expect(seen).toEqual(['Picking the cubes that answer it', 'table'])
  })

  it('reuses the conversation for a follow-up and keeps one conversation per scope', async () => {
    server.scripts.push(answerScript(), answerScript({ id: 't2' }), answerScript({ id: 't3' }))
    await useChatStore.getState().ask('', 'Bookings by month')
    await useChatStore.getState().ask('', 'and as a line chart')
    await useChatStore.getState().ask('Sales', 'Sales by month')
    expect(server.calls.map(c => c.path)).toEqual(['/conversations/c1/ask', '/conversations/c1/ask', '/conversations/c2/ask'])
    expect(conv().turns).toHaveLength(2)
    expect(conv('Sales').turns).toHaveLength(1)
  })

  it('an error event shows the plain message and the details', async () => {
    server.scripts.push(async onEvent => {
      onEvent('step', { text: 'Pulling the data' })
      onEvent('error', { message: "The cube server didn't answer.", details: 'Timeout' })
    })
    await useChatStore.getState().ask('', 'Bookings by month')
    expect(conv().turns[0]).toMatchObject({ status: 'error', error: "The cube server didn't answer.", details: 'Timeout' })
  })

  it('a refused request becomes an error turn', async () => {
    server.scripts.push(async () => { throw new ApiError(500, 'The server had a problem.', 'Traceback ...') })
    await useChatStore.getState().ask('', 'Bookings by month')
    expect(conv().turns[0]).toMatchObject({ status: 'error', error: 'The server had a problem.', details: 'Traceback ...' })
  })
})

describe('clarifying questions', () => {
  it('typed text answers the open question and asks again with the clarification', async () => {
    server.scripts.push(async onEvent => {
      onEvent('clarify', { question: 'Which errors do you mean?', options: ['Booking errors', 'Payment errors'] })
      onEvent('done', { turn: turn({ table: null, chart: null, query: '', clarify: { question: 'Which errors do you mean?', options: ['Booking errors', 'Payment errors'] } }) })
    }, answerScript({ id: 't2' }))
    await useChatStore.getState().ask('', 'Compare errors this week with last week')
    expect(conv().turns[0].clarify?.question).toBe('Which errors do you mean?')

    await useChatStore.getState().ask('', 'Booking errors')
    expect(server.calls[1].body).toEqual({
      question: 'Compare errors this week with last week',
      clarification: { question: 'Which errors do you mean?', answer: 'Booking errors' },
    })
    const [asked, answered] = conv().turns
    expect(asked.answered).toBe(true)
    expect(answered.question).toBe('Compare errors this week with last week → Booking errors')
    expect(answered.status).toBe('done')
  })
})

describe('stopping', () => {
  it('stop aborts the stream and keeps what arrived', async () => {
    let started!: () => void
    const waiting = new Promise<void>(r => { started = r })
    server.scripts.push((onEvent, signal) => new Promise<void>((_, reject) => {
      onEvent('step', { text: 'Understanding the question' })
      signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
      started()
    }))
    const asking = useChatStore.getState().ask('', 'Bookings by month')
    await waiting
    expect(conv().turns[0].status).toBe('streaming')
    // another question waits while one is streaming
    await useChatStore.getState().ask('', 'Sales by month')
    expect(conv().turns).toHaveLength(1)

    useChatStore.getState().stopAll()
    await asking
    expect(conv().turns[0]).toMatchObject({ status: 'stopped', steps: ['Understanding the question'] })

    // ask again: the same question, in its place
    server.scripts.push(answerScript())
    await useChatStore.getState().retry('', conv().turns[0].key)
    expect(conv().turns).toHaveLength(1)
    expect(conv().turns[0].status).toBe('done')
  })
})

describe('after the answer', () => {
  it('Change chart redraws only the chart and keeps the written answer', async () => {
    server.scripts.push(answerScript())
    await useChatStore.getState().ask('', 'Bookings by month')
    const key = conv().turns[0].key
    await useChatStore.getState().redraw('', key, 'as a line chart')
    expect(server.posts[server.posts.length - 1]).toEqual({ path: '/conversations/c1/turns/t1/chart', body: { request: 'as a line chart' } })
    expect(conv().turns[0].chart).toMatchObject({ kind: 'line', summary: 'Bookings grew.' })
    expect(conv().turns[0].redrawing).toBe(false)
    expect(server.calls).toHaveLength(1) // no new question
  })

  it('Mark as correct', async () => {
    server.scripts.push(answerScript())
    await useChatStore.getState().ask('', 'Bookings by month')
    await useChatStore.getState().verify('', conv().turns[0].key)
    expect(server.posts[server.posts.length - 1]).toEqual({ path: '/answers/5/verify', body: { verified: true } })
    expect(conv().turns[0].verified).toBe(true)
  })

  it('New chat starts afresh with a new conversation', async () => {
    server.scripts.push(answerScript(), answerScript())
    await useChatStore.getState().ask('', 'Bookings by month')
    useChatStore.getState().newChat('')
    expect(conv()).toEqual({ id: null, turns: [] })
    expect(JSON.parse(sessionStorage.getItem('chat.conversations')!)).toEqual({})
    await useChatStore.getState().ask('', 'Bookings by month')
    expect(conv().id).toBe('c2')
  })
})

describe('after a reload', () => {
  it('reads the conversation back from the server', async () => {
    sessionStorage.setItem('chat.conversations', JSON.stringify({ '': 'c9' }))
    server.gets['/conversations/c9'] = { id: 'c9', scope: '', turns: [turn(), turn({ id: 't2', question: 'and by week' })] }
    await useChatStore.getState().restore('')
    expect(conv().id).toBe('c9')
    expect(conv().turns.map(t => [t.id, t.status])).toEqual([['t1', 'done'], ['t2', 'done']])
  })

  it('follows a question the server was still answering, then shows its answer', async () => {
    vi.useFakeTimers()
    try {
      sessionStorage.setItem('chat.conversations', JSON.stringify({ '': 'c9' }))
      const replies = [
        { id: 'c9', scope: '', turns: [turn()], pending: { question: 'and by week', steps: ['Understanding the question'] } },
        { id: 'c9', scope: '', turns: [turn()], pending: { question: 'and by week', steps: ['Understanding the question', 'Pulling the data'] } },
        { id: 'c9', scope: '', turns: [turn(), turn({ id: 't2', question: 'and by week' })], pending: null },
      ]
      server.gets['/conversations/c9'] = () => replies.shift()
      await useChatStore.getState().restore('')
      expect(conv().turns.map(t => [t.question, t.status])).toEqual([['Bookings by month', 'done'], ['and by week', 'streaming']])
      expect(conv().turns[1].steps).toEqual(['Understanding the question'])
      await useChatStore.getState().ask('', 'Sales by month') // waits: a question is being answered
      expect(server.calls).toHaveLength(0)

      await vi.advanceTimersByTimeAsync(FOLLOW_EVERY_MS)
      expect(conv().turns[1].steps).toEqual(['Understanding the question', 'Pulling the data'])
      await vi.advanceTimersByTimeAsync(FOLLOW_EVERY_MS)
      expect(conv().turns.map(t => [t.id, t.status])).toEqual([['t1', 'done'], ['t2', 'done']])
      expect(conv().turns[1]).toMatchObject({ table, chart })

      server.scripts.push(answerScript({ id: 't3', question: 'Sales by month' })) // free again
      await useChatStore.getState().ask('', 'Sales by month')
      expect(conv().turns.map(t => t.id)).toEqual(['t1', 't2', 't3'])
    } finally {
      vi.useRealTimers()
    }
  })

  it('Stop stops following (the server still finishes the answer)', async () => {
    vi.useFakeTimers()
    try {
      sessionStorage.setItem('chat.conversations', JSON.stringify({ '': 'c9' }))
      server.gets['/conversations/c9'] = { id: 'c9', scope: '', turns: [], pending: { question: 'Bookings by month', steps: [] } }
      await useChatStore.getState().restore('')
      useChatStore.getState().stop('')
      await vi.advanceTimersByTimeAsync(FOLLOW_EVERY_MS)
      expect(conv().turns.map(t => t.status)).toEqual(['stopped'])
    } finally {
      vi.useRealTimers()
    }
  })

  it('forgets a conversation the server no longer has', async () => {
    sessionStorage.setItem('chat.conversations', JSON.stringify({ '': 'gone' }))
    await useChatStore.getState().restore('')
    expect(conv().id).toBeNull()
    expect(JSON.parse(sessionStorage.getItem('chat.conversations')!)).toEqual({})
  })
})
