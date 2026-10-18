// Follows a server job live: its event stream (GET /jobs/{id}/events: `line {"text"}` … `done {"status"}`),
// then one read of GET /jobs/{id} for the final state (status, error, every line). If the stream can't be
// opened or drops, it polls GET /jobs/{id} instead until the job ends.
import { useEffect, useReducer, useRef } from 'react'
import { api, ApiError } from '../../api/client'
import type { Job } from '../../api/types'
import { idleJob, jobReducer, type JobProgress } from './jobProgress'

const POLL_MS = 1500

export function useJobProgress(id: string | null, onFinish?: (status: 'done' | 'failed') => void): JobProgress {
  const [state, dispatch] = useReducer(jobReducer, idleJob)
  const finished = useRef(onFinish)
  useEffect(() => { finished.current = onFinish }, [onFinish])

  useEffect(() => {
    if (!id) {
      dispatch({ type: 'reset' })
      return
    }
    dispatch({ type: 'started', id })
    let closed = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let source: EventSource | null = null

    const poll = async () => {
      try {
        const job = await api.get<Job>(`/jobs/${encodeURIComponent(id)}`)
        if (closed) return
        dispatch({ type: 'snapshot', job })
        if (job.status !== 'running') {
          finished.current?.(job.status)
          return
        }
      } catch (err) {
        if (closed) return
        if (err instanceof ApiError && (err.status === 404 || err.status === 401)) {
          dispatch({ type: 'fail', error: err.status === 404
            ? 'The server no longer knows this job (it may have restarted). Start it again.'
            : err.message })
          finished.current?.('failed')
          return
        }
        // the server is busy or restarting: keep asking
      }
      timer = setTimeout(poll, POLL_MS)
    }

    if (typeof EventSource === 'undefined') {
      void poll()
    } else {
      source = new EventSource(`/api/jobs/${encodeURIComponent(id)}/events`)
      source.addEventListener('line', (e) => {
        try {
          const text = JSON.parse((e as MessageEvent).data)?.text
          if (typeof text === 'string') dispatch({ type: 'line', text })
        } catch { /* not JSON: ignore */ }
      })
      source.addEventListener('done', () => {
        source?.close()
        source = null
        void poll()   // the final state: status, error and the complete list of lines
      })
      source.onerror = () => {
        if (!source) return
        source.close()   // stop the browser reconnecting (it would replay every line again)
        source = null
        void poll()
      }
    }
    return () => {
      closed = true
      source?.close()
      if (timer) clearTimeout(timer)
    }
  }, [id])

  return state
}
