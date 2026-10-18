// The only way the app talks to the server: JSON calls and Server-Sent Event streams under /api.
// Writes carry the X-Requested-With header the server checks (protection against cross-site requests).

export class ApiError extends Error {
  status: number
  details?: string
  constructor(status: number, message: string, details?: string) {
    super(message)
    this.status = status
    this.details = details
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (method !== 'GET') headers['X-Requested-With'] = 'bookings-assistant'
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(`/api${path}`, {
    method, headers, credentials: 'same-origin', body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = res.statusText, details: string | undefined
    try { const j = await res.json(); detail = j.detail ?? detail; details = j.details } catch { /* not JSON */ }
    throw new ApiError(res.status, detail, details)
  }
  return (res.status === 204 ? undefined : await res.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body ?? {}),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body ?? {}),
  del: <T>(path: string) => request<T>('DELETE', path),
}

/** POST that answers with a Server-Sent Event stream: calls onEvent(name, data) for each event as it
 * arrives. Resolves when the stream ends; abort with the signal. */
export async function stream(path: string, body: unknown, onEvent: (event: string, data: any) => void,
                             signal?: AbortSignal): Promise<void> {
  const res = await fetch(`/api${path}`, {
    method: 'POST', credentials: 'same-origin', signal,
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', 'X-Requested-With': 'bookings-assistant' },
    body: JSON.stringify(body),
  })
  if (!res.ok || !res.body) {
    let detail = res.statusText
    try { detail = (await res.json()).detail ?? detail } catch { /* not JSON */ }
    throw new ApiError(res.status, detail)
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    let cut: number
    while ((cut = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, cut)
      buffer = buffer.slice(cut + 2)
      let event = 'message', data = ''
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trimStart()
      }
      if (data) onEvent(event, JSON.parse(data))
    }
  }
}
