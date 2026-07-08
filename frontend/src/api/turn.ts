import type { TurnEvent } from '../types'

/**
 * POST /turn returns an SSE stream. EventSource can't send a POST body, so
 * this hand-rolls the SSE framing: read chunks, split on blank-line event
 * boundaries, keep only `data:` lines (sse-starlette's `: ping - ...`
 * keepalive comments are dropped since they never start with `data:`).
 */
export async function streamTurn(
  playerId: string,
  message: string,
  onEvent: (event: TurnEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch('/api/turn', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ player_id: playerId, message }),
    signal,
  })
  if (!response.ok || !response.body) {
    throw new Error(`turn request failed: ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    // Normalize CRLF to LF here — sse-starlette/uvicorn on Windows (or a
    // proxy hop) can emit \r\n, which silently breaks a strict "\n\n"
    // boundary match: the loop below would just never find an event.
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')

    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const rawEvent = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)

      const dataLines = rawEvent
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())
      if (dataLines.length > 0) {
        onEvent(JSON.parse(dataLines.join('\n')) as TurnEvent)
      }

      boundary = buffer.indexOf('\n\n')
    }
  }
}
