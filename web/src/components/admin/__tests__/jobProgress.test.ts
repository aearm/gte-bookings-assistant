import { describe, expect, it } from 'vitest'
import type { Job } from '../../../api/types'
import { idleJob, isActive, isFinished, jobHeadline, jobReducer, type JobAction, type JobProgress } from '../jobProgress'

const run = (actions: JobAction[], from: JobProgress = idleJob) => actions.reduce(jobReducer, from)
const words = { running: 'Building…', done: 'Ready', failed: 'Could not build' }

describe('jobReducer', () => {
  it('follows a job from start to done, line by line', () => {
    const s = run([
      { type: 'start' },
      { type: 'started', id: 'j1' },
      { type: 'line', text: 'Reading 2 cubes...' },
      { type: 'line', text: '✓ Read Bookings (1/2)' },
      { type: 'done', status: 'done' },
    ])
    expect(s).toEqual({ id: 'j1', phase: 'done', lines: ['Reading 2 cubes...', '✓ Read Bookings (1/2)'], error: null })
    expect(isFinished(s)).toBe(true)
    expect(jobHeadline(s, words)).toBe('Ready')
  })

  it('is active while starting and running', () => {
    const starting = run([{ type: 'start' }])
    expect(isActive(starting)).toBe(true)
    expect(jobHeadline(starting, words)).toBe('Starting…')
    const running = run([{ type: 'started', id: 'j1' }])
    expect(isActive(running)).toBe(true)
    expect(jobHeadline(running, words)).toBe('Building…')
  })

  it('takes the complete list of lines from a snapshot (polling or the final read)', () => {
    const job: Job = { id: 'j1', kind: 'layer', status: 'running', lines: ['a', 'b', 'c'] }
    const s = run([{ type: 'started', id: 'j1' }, { type: 'line', text: 'a' }, { type: 'snapshot', job }])
    expect(s.lines).toEqual(['a', 'b', 'c'])
    expect(s.phase).toBe('running')
  })

  it('keeps its own lines when a snapshot has fewer', () => {
    const job: Job = { id: 'j1', kind: 'layer', status: 'running', lines: ['a'] }
    const s = run([{ type: 'started', id: 'j1' }, { type: 'line', text: 'a' }, { type: 'line', text: 'b' }, { type: 'snapshot', job }])
    expect(s.lines).toEqual(['a', 'b'])
  })

  it('records the error of a failed job', () => {
    const job: Job = { id: 'j1', kind: 'layer', status: 'failed', lines: ['a'], error: 'No Claude API key is set.' }
    const s = run([{ type: 'started', id: 'j1' }, { type: 'snapshot', job }])
    expect(s.phase).toBe('failed')
    expect(s.error).toBe('No Claude API key is set.')
    expect(jobHeadline(s, words)).toBe('Could not build')
  })

  it('ignores a snapshot of another job and lines after the end', () => {
    const other: Job = { id: 'j2', kind: 'layer', status: 'done', lines: ['x'] }
    let s = run([{ type: 'started', id: 'j1' }, { type: 'snapshot', job: other }])
    expect(s).toEqual({ id: 'j1', phase: 'running', lines: [], error: null })
    s = run([{ type: 'done', status: 'done' }, { type: 'line', text: 'late' }], s)
    expect(s.lines).toEqual([])
  })

  it('starts empty for a new job id, and keeps the state for the same one', () => {
    const first = run([{ type: 'started', id: 'j1' }, { type: 'line', text: 'a' }])
    expect(jobReducer(first, { type: 'started', id: 'j1' }).lines).toEqual(['a'])
    expect(jobReducer(first, { type: 'started', id: 'j2' })).toEqual({ id: 'j2', phase: 'running', lines: [], error: null })
  })

  it('fails when the job could not be started, and resets', () => {
    const s = run([{ type: 'start' }, { type: 'fail', error: 'Sign in as admin to do this.' }])
    expect(s.phase).toBe('failed')
    expect(s.error).toBe('Sign in as admin to do this.')
    expect(jobReducer(s, { type: 'reset' })).toEqual(idleJob)
  })
})
