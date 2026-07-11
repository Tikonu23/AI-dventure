import type { StructuredResponse } from '../types'

/** Someone else's action won this turn — first-come-wins, not queued. */
export class TurnRejectedError extends Error {
  actor: string

  constructor(actor: string) {
    super(`turn in progress (${actor} is acting)`)
    this.name = 'TurnRejectedError'
    this.actor = actor
  }
}

/**
 * Submit a turn. All rendering (streamed narrative, tool calls,
 * turn_complete) arrives via the room event stream, not this response —
 * the return value only matters for error handling.
 */
export async function postTurn(
  roomCode: string,
  token: string,
  message: string,
  logPlayerAction: boolean,
): Promise<StructuredResponse> {
  const response = await fetch(`/api/games/${encodeURIComponent(roomCode)}/turn`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, message, log_player_action: logPlayerAction }),
  })
  if (response.status === 409) {
    const body = (await response.json()) as { detail?: { actor?: string } }
    throw new TurnRejectedError(body.detail?.actor ?? 'another adventurer')
  }
  if (!response.ok) {
    throw new Error(`turn request failed: ${response.status}`)
  }
  const body = (await response.json()) as { response: StructuredResponse }
  return body.response
}
