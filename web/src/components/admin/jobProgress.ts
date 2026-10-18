// The progress of a server job (data-layer build, cube map draft) as the page shows it.
// Fed by the job's event stream (line / done) or, if the stream drops, by polling GET /jobs/{id}.
import type { Job } from '../../api/types'

export type JobPhase = 'idle' | 'starting' | 'running' | 'done' | 'failed'
export type JobProgress = { id: string | null; phase: JobPhase; lines: string[]; error: string | null }

export type JobAction =
  | { type: 'start' }                                   // asked the server to start it
  | { type: 'started'; id: string }                     // the server answered with the job id
  | { type: 'line'; text: string }                      // one progress line from the stream
  | { type: 'snapshot'; job: Job }                      // the whole job (polling, or the final read)
  | { type: 'done'; status: 'done' | 'failed'; error?: string | null }
  | { type: 'fail'; error: string }                     // it couldn't be started, or the server is gone
  | { type: 'reset' }

export const idleJob: JobProgress = { id: null, phase: 'idle', lines: [], error: null }

export const isActive = (p: JobProgress) => p.phase === 'starting' || p.phase === 'running'
export const isFinished = (p: JobProgress) => p.phase === 'done' || p.phase === 'failed'

export function jobReducer(state: JobProgress, action: JobAction): JobProgress {
  switch (action.type) {
    case 'start':
      return { id: null, phase: 'starting', lines: [], error: null }
    case 'started':
      // a new job, or the same one again (a page coming back to a job that is still running)
      return state.id === action.id ? { ...state, phase: isFinished(state) ? state.phase : 'running' }
        : { id: action.id, phase: 'running', lines: [], error: null }
    case 'line':
      if (isFinished(state)) return state     // late lines after the end change nothing
      return { ...state, phase: 'running', lines: [...state.lines, action.text] }
    case 'snapshot': {
      const job = action.job
      if (state.id && job.id && job.id !== state.id) return state   // an answer about another job
      const phase: JobPhase = job.status === 'running' ? 'running' : job.status
      // the server's list is complete; keep ours only if it somehow has more
      const lines = (job.lines?.length ?? 0) >= state.lines.length ? [...(job.lines ?? [])] : state.lines
      return { id: job.id ?? state.id, phase, lines, error: job.status === 'failed' ? (job.error ?? state.error) : state.error }
    }
    case 'done':
      return { ...state, phase: action.status, error: action.status === 'failed' ? (action.error ?? state.error) : null }
    case 'fail':
      return { ...state, phase: 'failed', error: action.error }
    case 'reset':
      return idleJob
  }
}

/** The status line above the log: what is happening, in plain words. */
export function jobHeadline(p: JobProgress, words: { running: string; done: string; failed: string }): string {
  if (p.phase === 'done') return words.done
  if (p.phase === 'failed') return words.failed
  if (p.phase === 'starting') return 'Starting…'
  return words.running
}
