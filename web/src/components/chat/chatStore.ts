// The Chat page's conversations, one per "Data" scope, kept in memory so they survive leaving the page
// and coming back - an answer still on its way keeps arriving meanwhile. The conversation ids also go to
// sessionStorage, so a reload can read them back from the server (GET /conversations/{id}), including a
// question still being answered, which is then followed until its answer is there.
import { create } from 'zustand'
import { api, ApiError, stream } from '../../api/client'
import type { Chart, Conversation as ServerConversation, Turn } from '../../api/types'
import { applyEvent, failTurn, finishStream, fromServer, openQuestion, pendingTurn } from './turnEvents'
import type { Conversation, Sent, TurnView } from './types'

const IDS_KEY = 'chat.conversations' // {scope: conversation id}
const SCOPE_KEY = 'chat.scope'

function readIds(): Record<string, string> {
  try {
    const raw = globalThis.sessionStorage?.getItem(IDS_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch { return {} }
}

function writeId(scope: string, id: string | null): void {
  try {
    const ids = readIds()
    if (id) ids[scope] = id
    else delete ids[scope]
    globalThis.sessionStorage?.setItem(IDS_KEY, JSON.stringify(ids))
  } catch { /* storage blocked: the conversation just won't survive a reload */ }
}

function readScope(): string | null {
  try { return globalThis.sessionStorage?.getItem(SCOPE_KEY) ?? null } catch { return null }
}

function writeScope(scope: string): void {
  try { globalThis.sessionStorage?.setItem(SCOPE_KEY, scope) } catch { /* ignore */ }
}

const EMPTY: Conversation = { id: null, turns: [] }

/** Running streams (and answers being followed), by scope (not in the state: not something to render). */
const running = new Map<string, AbortController>()

/** How often, and how long, a question answered for an earlier page is checked on. */
export const FOLLOW_EVERY_MS = 2000
const FOLLOW_FOR_MS = 15 * 60_000

const pause = (ms: number, signal: AbortSignal) => new Promise<void>(resolve => {
  const timer = setTimeout(resolve, ms)
  signal.addEventListener('abort', () => { clearTimeout(timer); resolve() }, { once: true })
})

export type ChatState = {
  /** The "Data" picked: "" = all the data, else a cube. null until /info says what there is. */
  scope: string | null
  conversations: Record<string, Conversation>
  setScope: (scope: string) => void
  /** Typed text or a suggestion: answers the open clarifying question if there is one, else asks. */
  ask: (scope: string, text: string) => Promise<void>
  /** An answer to the open clarifying question (an option or free text). */
  reply: (scope: string, answer: string) => Promise<void>
  /** Ask a stopped (or failed) turn again, in its place. */
  retry: (scope: string, key: string) => Promise<void>
  newChat: (scope: string) => void
  /** After a reload: read this scope's conversation back from the server. */
  restore: (scope: string) => Promise<void>
  /** "Change chart": the same numbers drawn as described (no new query). */
  redraw: (scope: string, key: string, request: string) => Promise<void>
  /** "Mark as correct" (admin). Throws on failure. */
  verify: (scope: string, key: string) => Promise<void>
  /** Stop every running answer (leaving the page). */
  stopAll: () => void
  stop: (scope: string) => void
}

export const useChatStore = create<ChatState>()((set, get) => {
  const conv = (scope: string): Conversation => get().conversations[scope] ?? EMPTY

  const patchConv = (scope: string, fn: (c: Conversation) => Conversation) =>
    set(s => ({ conversations: { ...s.conversations, [scope]: fn(s.conversations[scope] ?? EMPTY) } }))

  const patchTurn = (scope: string, key: string, fn: (t: TurnView) => TurnView) =>
    patchConv(scope, c => ({ ...c, turns: c.turns.map(t => (t.key === key ? fn(t) : t)) }))

  const busy = (scope: string) => running.has(scope) || conv(scope).turns.some(t => t.status === 'streaming')

  /** Send a question and stream its answer into a new turn (or into `replace`'s place). */
  async function run(scope: string, sent: Sent, shownAs?: string, replace?: string): Promise<void> {
    if (busy(scope)) return
    const turn = pendingTurn(sent, shownAs)
    const key = turn.key
    patchConv(scope, c => ({
      ...c,
      turns: replace ? c.turns.map(t => (t.key === replace ? turn : t)) : [...c.turns, turn],
    }))
    const controller = new AbortController()
    running.set(scope, controller)
    try {
      let id = conv(scope).id
      if (!id) {
        id = (await api.post<{ id: string }>('/conversations', { scope })).id
        if (controller.signal.aborted) throw new DOMException('Stopped', 'AbortError') // e.g. New chat meanwhile
        patchConv(scope, c => ({ ...c, id }))
        writeId(scope, id)
      }
      const body = sent.clarification ? { question: sent.question, clarification: sent.clarification } : { question: sent.question }
      await stream(`/conversations/${id}/ask`, body,
        (event, data) => patchTurn(scope, key, t => applyEvent(t, event, data)), controller.signal)
      patchTurn(scope, key, t => finishStream(t, false))
    } catch (err) {
      if (controller.signal.aborted) {
        patchTurn(scope, key, t => finishStream(t, true))
      } else if (err instanceof ApiError && err.status === 404) {
        patchTurn(scope, key, t => failTurn(t, 'This conversation is no longer on the server (it may have restarted). '
          + 'Click New chat and ask again.', err.message))
      } else {
        const e = err as ApiError
        patchTurn(scope, key, t => failTurn(t, e?.message || 'Something went wrong.', e?.details))
      }
    } finally {
      if (running.get(scope) === controller) running.delete(scope)
    }
  }

  /** A question the server was still answering when this page read the conversation (after a reload):
   *  read the conversation again every few seconds, showing the progress, until the answer is there.
   *  Stop (or New chat) stops following; the server still finishes it. */
  async function follow(scope: string, id: string, key: string): Promise<void> {
    const controller = new AbortController()
    running.set(scope, controller)
    const until = Date.now() + FOLLOW_FOR_MS
    try {
      while (Date.now() < until) {
        await pause(FOLLOW_EVERY_MS, controller.signal)
        if (controller.signal.aborted || conv(scope).id !== id) break
        const saved = await api.get<ServerConversation>(`/conversations/${id}`)
        if (conv(scope).id !== id) break
        const pending = saved.pending
        if (!pending) { // answered: its turn (and anything else new) takes the waiting one's place
          patchConv(scope, c => {
            const known = new Set(c.turns.filter(t => t.id).map(t => t.id))
            const added = (saved.turns ?? []).filter((t: Turn) => !known.has(t.id)).map(fromServer)
            return { ...c, turns: [...c.turns.filter(t => t.key !== key), ...added] }
          })
          return
        }
        patchTurn(scope, key, t => ({ ...t, steps: [...pending.steps] }))
      }
      if (controller.signal.aborted) patchTurn(scope, key, t => finishStream(t, true))
      else if (conv(scope).id === id) patchTurn(scope, key, t => failTurn(t, 'The answer is taking too long. Ask again in a moment.'))
    } catch (err) {
      const gone = err instanceof ApiError && err.status === 404
      patchTurn(scope, key, t => failTurn(t, gone
        ? 'This conversation is no longer on the server (it may have restarted). Click New chat and ask again.'
        : 'The answer could not be read. Reload the page to see it.', (err as ApiError)?.message))
    } finally {
      if (running.get(scope) === controller) running.delete(scope)
    }
  }

  return {
    scope: readScope(),
    conversations: {},

    setScope(scope) {
      writeScope(scope)
      set({ scope })
    },

    async ask(scope, text) {
      const question = text.trim()
      if (!question) return
      if (openQuestion(conv(scope).turns)) return get().reply(scope, question)
      return run(scope, { question })
    },

    async reply(scope, answer) {
      const text = answer.trim()
      const open = openQuestion(conv(scope).turns)
      if (!text || !open?.clarify || busy(scope)) return
      patchTurn(scope, open.key, t => ({ ...t, answered: true }))
      const original = open.sent.question
      return run(scope, { question: original, clarification: { question: open.clarify.question, answer: text } },
        `${original} → ${text}`)
    },

    async retry(scope, key) {
      const turn = conv(scope).turns.find(t => t.key === key)
      if (!turn) return
      return run(scope, turn.sent, turn.question, key)
    },

    newChat(scope) {
      get().stop(scope)
      writeId(scope, null)
      patchConv(scope, () => ({ id: null, turns: [] }))
    },

    async restore(scope) {
      const c = conv(scope)
      if (c.id || c.turns.length || c.loading) return
      const id = readIds()[scope]
      if (!id) return
      patchConv(scope, x => ({ ...x, id, loading: true }))
      try {
        const saved = await api.get<ServerConversation>(`/conversations/${id}`)
        const pending = saved.pending
        const waiting = pending ? { ...pendingTurn({ question: pending.question }), steps: [...pending.steps] } : null
        patchConv(scope, x => (x.id !== id ? x : {
          id, turns: [...(saved.turns ?? []).map(fromServer), ...x.turns, ...(waiting ? [waiting] : [])], loading: false,
        }))
        if (waiting) void follow(scope, id, waiting.key)
      } catch {
        // gone (server restarted) or unreachable: start afresh
        writeId(scope, null)
        patchConv(scope, x => (x.id !== id ? x : { ...x, id: null, loading: false }))
      }
    },

    async redraw(scope, key, request) {
      const c = conv(scope)
      const turn = c.turns.find(t => t.key === key)
      if (!turn || !c.id || !turn.id || !request.trim()) return
      patchTurn(scope, key, t => ({ ...t, redrawing: true, chartError: undefined }))
      try {
        const res = await api.post<{ chart: Chart }>(`/conversations/${c.id}/turns/${turn.id}/chart`, { request: request.trim() })
        // same numbers, so the written answer stays (views/chat.py restyle)
        patchTurn(scope, key, t => ({
          ...t, redrawing: false,
          chart: res.chart ? { ...res.chart, summary: t.chart?.summary || res.chart.summary } : t.chart,
        }))
      } catch (err) {
        patchTurn(scope, key, t => ({ ...t, redrawing: false, chartError: (err as Error)?.message || 'The chart could not be drawn.' }))
      }
    },

    async verify(scope, key) {
      const turn = conv(scope).turns.find(t => t.key === key)
      if (!turn?.answer_id) return
      await api.post(`/answers/${turn.answer_id}/verify`, { verified: true })
      patchTurn(scope, key, t => ({ ...t, verified: true }))
    },

    stopAll() { // (not when leaving the page: an answer on its way keeps arriving, to be seen on return)
      for (const controller of running.values()) controller.abort()
      running.clear() // free at once: a question asked right after isn't refused as "busy"
    },

    stop(scope) {
      running.get(scope)?.abort()
      running.delete(scope)
    },
  }
})

/** For tests: forget every conversation and running stream. */
export function resetChatStore(): void {
  for (const controller of running.values()) controller.abort()
  running.clear()
  useChatStore.setState({ scope: null, conversations: {} })
}
