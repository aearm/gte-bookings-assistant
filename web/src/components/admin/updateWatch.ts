// App updates: comparing versions, the last update's outcome, and following an update while the app
// stops, updates and starts again (by asking /health every few seconds).
import { whenText } from './format'
import type { LastUpdate, UpdatesInfo } from './types'

function parts(version: string): number[] {
  return version.trim().replace(/^[vV]/, '').split(/[.\-+]/).map((p) => Number.parseInt(p, 10)).filter((n) => !Number.isNaN(n))
}

/** Is `latest` newer than `current`? ("1.10.0" > "1.9.2"; a leading v is ignored) */
export function isNewer(latest: string | null | undefined, current: string | null | undefined): boolean {
  if (!latest) return false
  const a = parts(latest), b = parts(current ?? '0')
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const x = a[i] ?? 0, y = b[i] ?? 0
    if (x !== y) return x > y
  }
  return false
}

export type UpdateNote =
  | { kind: 'running' }
  | { kind: 'ok'; text: string }
  | { kind: 'failed'; text: string }
  | null

/** The `status` of GET /updates in plain words: an update running, or how the last one went. */
export function describeUpdateStatus(status: string | LastUpdate | null | undefined): UpdateNote {
  if (!status) return null
  if (typeof status === 'string') return status === 'updating' || status === 'running' ? { kind: 'running' } : null
  if ((status as { updating?: boolean }).updating) return { kind: 'running' }
  if (!status.to) return null
  const when = whenText(status.time, true).replace(/ (\d\d:\d\d)$/, ', $1')
  return status.ok
    ? { kind: 'ok', text: `Last update: ${status.from ?? '?'} → ${status.to}${when ? ` on ${when}` : ''}.` }
    : { kind: 'failed', text: `The update to ${status.to}${when ? ` on ${when}` : ''} didn't work: ${status.error ?? ''}`.trim() }
}

export type CheckResult = 'newer' | 'latest' | 'none' | 'failed' | 'updating'

/** What a check for updates found: the server's status when it names one, else worked out from the
 * versions. */
export function checkResult(info: UpdatesInfo): CheckResult {
  switch (info.status) {
    case 'available': return 'newer'
    case 'up_to_date': return 'latest'
    case 'no_release': return 'none'
    case 'check_failed': return 'failed'
    case 'updating': return 'updating'
  }
  if (!info.latest) return 'none'
  return isNewer(info.latest, info.current) ? 'newer' : 'latest'
}

// ---------------------------------------------------------------- following an update --

export type UpdateWatch = {
  phase: 'idle' | 'waiting' | 'restarting' | 'done' | 'slow' | 'failed'
  from: string        // the version before
  to: string          // the version being installed
  startedAt: number
  sawDown: boolean    // the server went away at least once (it restarts during the update)
  error: string
}

export const idleWatch: UpdateWatch = { phase: 'idle', from: '', to: '', startedAt: 0, sawDown: false, error: '' }

/** Taking longer than this: say so (the update keeps going; the page just stops promising). */
export const UPDATE_SLOW_MS = 10 * 60_000

export function startWatch(from: string, to: string, now: number): UpdateWatch {
  return { phase: 'waiting', from, to, startedAt: now, sawDown: false, error: '' }
}

/** One look at the server moves the watch on: /health (ok with its version, or no answer) and, while the
 * old version still runs, the error of a download that failed after Update was pressed. */
export function stepWatch(w: UpdateWatch, probe: { ok: boolean; version?: string; error?: string }, now: number): UpdateWatch {
  if (w.phase === 'idle' || w.phase === 'done' || w.phase === 'failed') return w
  if (probe.ok && probe.version) {
    const updated = probe.version === w.to || (probe.version !== w.from && isNewer(probe.version, w.from))
    if (updated) return { ...w, phase: 'done' }
  }
  if (probe.ok && probe.error && !w.sawDown) return { ...w, phase: 'failed', error: probe.error }
  const sawDown = w.sawDown || !probe.ok
  if (now - w.startedAt > UPDATE_SLOW_MS) return { ...w, sawDown, phase: 'slow' }
  return { ...w, sawDown, phase: probe.ok ? 'waiting' : 'restarting' }
}

export function watchText(w: UpdateWatch): string {
  switch (w.phase) {
    case 'waiting':
      return w.sawDown ? 'Starting the new version…' : `Downloading version ${w.to} and getting ready to update…`
    case 'restarting':
      return 'The app is stopping, updating and starting again (about a minute)…'
    case 'done':
      return `Updated to version ${w.to}. Reload the page to use it.`
    case 'slow':
      return "It's taking longer than usual. Reload this page in a minute; if the old version is still shown, check for updates again."
    case 'failed':
      return `The update to ${w.to} didn't work: ${w.error}`
    default:
      return ''
  }
}
