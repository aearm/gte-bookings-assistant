// What the Chat page keeps for each answer: the server's Turn (docs/api.md) plus what the page itself
// needs while it streams and after (progress lines, the question as shown, redraws, verified...).
import type { Turn } from '../../api/types'

export type TurnStatus = 'streaming' | 'done' | 'error' | 'stopped'

/** What was sent to /ask for this turn (to ask again after a stop). */
export type Sent = { question: string; clarification?: { question: string; answer: string } }

export type TurnView = Turn & {
  /** The page's own key for this turn (the server's id arrives with `done`). */
  key: string
  status: TurnStatus
  /** Progress lines (`step` events), in order. */
  steps: string[]
  sent: Sent
  /** Error details (technical text, for support). */
  details?: string
  /** Text of `answer` events, if the server streams the written answer separately from the chart. */
  answerText?: string
  /** A clarifying question that has been answered (its buttons are disabled). */
  answered?: boolean
  /** Marked as correct by an admin in this session. */
  verified?: boolean
  /** "Change chart" is running for this turn. */
  redrawing?: boolean
  /** Why the last "Change chart" failed. */
  chartError?: string
}

export type Conversation = {
  /** Server conversation id; null until the first question is asked. */
  id: string | null
  turns: TurnView[]
  /** Loading the conversation back from the server after a reload. */
  loading?: boolean
}

export type HistoryItem = { time: string; question: string; rows: number; title: string }
