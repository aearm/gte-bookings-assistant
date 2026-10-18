import { describe, expect, it } from 'vitest'
import type { UpdatesInfo } from '../types'
import { checkResult, describeUpdateStatus, idleWatch, isNewer, startWatch, stepWatch, UPDATE_SLOW_MS, watchText } from '../updateWatch'

describe('isNewer', () => {
  it('compares versions number by number', () => {
    expect(isNewer('1.2.0', '1.1.0')).toBe(true)
    expect(isNewer('1.10.0', '1.9.2')).toBe(true)
    expect(isNewer('v2.0.0', '1.9.9')).toBe(true)
    expect(isNewer('1.1.0', '1.1.0')).toBe(false)
    expect(isNewer('1.1', '1.1.0')).toBe(false)
    expect(isNewer('1.0.9', '1.1.0')).toBe(false)
    expect(isNewer(null, '1.1.0')).toBe(false)
  })
})

describe('describeUpdateStatus', () => {
  it('says when an update is running', () => {
    expect(describeUpdateStatus('updating')).toEqual({ kind: 'running' })
    expect(describeUpdateStatus({ updating: true } as never)).toEqual({ kind: 'running' })
  })

  it('tells how the last update went', () => {
    expect(describeUpdateStatus({ time: '2026-10-02T09:15:00', ok: true, from: '1.0.0', to: '1.1.0' }))
      .toEqual({ kind: 'ok', text: 'Last update: 1.0.0 → 1.1.0 on 2 Oct 2026, 09:15.' })
    expect(describeUpdateStatus({ time: '2026-10-02T09:15:00', ok: false, from: '1.0.0', to: '1.1.0', error: 'disk full' }))
      .toEqual({ kind: 'failed', text: "The update to 1.1.0 on 2 Oct 2026, 09:15 didn't work: disk full" })
  })

  it('says nothing when there is nothing to say', () => {
    expect(describeUpdateStatus(null)).toBeNull()
    expect(describeUpdateStatus('idle')).toBeNull()
    expect(describeUpdateStatus({})).toBeNull()
  })
})

describe('checkResult', () => {
  const info = (over: Partial<UpdatesInfo>): UpdatesInfo => ({
    current: '1.1.0', latest: '', published: '', notes: '', developer_copy: false, status: null, ...over,
  })

  it("follows the server's status", () => {
    expect(checkResult(info({ status: 'available', latest: '1.2.0' }))).toBe('newer')
    expect(checkResult(info({ status: 'up_to_date', latest: '1.1.0' }))).toBe('latest')
    expect(checkResult(info({ status: 'no_release' }))).toBe('none')
    expect(checkResult(info({ status: 'check_failed', error: 'offline' }))).toBe('failed')
    expect(checkResult(info({ status: 'updating' }))).toBe('updating')
  })

  it('compares the versions when the status names none of those', () => {
    expect(checkResult(info({ latest: '1.2.0' }))).toBe('newer')
    expect(checkResult(info({ latest: '1.1.0' }))).toBe('latest')
    expect(checkResult(info({ latest: null }))).toBe('none')
  })
})

describe('following an update', () => {
  const up = (version: string) => ({ ok: true, version })
  const down = { ok: false }

  it('goes waiting → restarting → done when the new version answers', () => {
    let w = startWatch('1.1.0', '1.2.0', 0)
    expect(w.phase).toBe('waiting')
    w = stepWatch(w, up('1.1.0'), 3000)
    expect(w.phase).toBe('waiting')
    expect(watchText(w)).toContain('Downloading version 1.2.0')
    w = stepWatch(w, down, 6000)
    expect(w.phase).toBe('restarting')
    w = stepWatch(w, up('1.1.0'), 9000)            // the old one still answering for a moment
    expect(w).toMatchObject({ phase: 'waiting', sawDown: true })
    expect(watchText(w)).toBe('Starting the new version…')
    w = stepWatch(w, up('1.2.0'), 12000)
    expect(w.phase).toBe('done')
    expect(watchText(w)).toBe('Updated to version 1.2.0. Reload the page to use it.')
    expect(stepWatch(w, down, 15000)).toBe(w)      // done stays done
  })

  it('says it is slow after ten minutes, and still notices the new version', () => {
    let w = stepWatch(startWatch('1.1.0', '1.2.0', 0), down, UPDATE_SLOW_MS + 1)
    expect(w.phase).toBe('slow')
    w = stepWatch(w, up('1.2.0'), UPDATE_SLOW_MS + 3000)
    expect(w.phase).toBe('done')
  })

  it('fails when the download went wrong while the old version still runs', () => {
    const w = stepWatch(startWatch('1.1.0', '1.2.0', 0), { ok: true, version: '1.1.0', error: 'Download failed.' }, 3000)
    expect(w.phase).toBe('failed')
    expect(watchText(w)).toBe("The update to 1.2.0 didn't work: Download failed.")
    expect(stepWatch(w, up('1.2.0'), 6000)).toBe(w)
  })

  it('does nothing while idle', () => {
    expect(stepWatch(idleWatch, up('9.9.9'), 1)).toBe(idleWatch)
  })
})
