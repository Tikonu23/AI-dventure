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
    const body = (await response.json()) as { detail?: { code?: string; actor?: string } }
    if (body.detail?.code === 'game_over') throw new Error('The story has already ended.')
    throw new TurnRejectedError(body.detail?.actor ?? 'another adventurer')
  }
  if (response.status === 403) {
    const body = (await response.json().catch(() => ({}))) as { detail?: { code?: string } }
    if (body.detail?.code === 'player_dead')
      throw new Error('Your character is dead — the story goes on without them.')
  }
  if (!response.ok) {
    throw new Error(`turn request failed: ${response.status}`)
  }
  const body = (await response.json()) as { response: StructuredResponse }
  return body.response
}

/** Release a turn that's blocked on a pending dice roll. */
export async function postRoll(roomCode: string, token: string): Promise<void> {
  const response = await fetch(`/api/games/${encodeURIComponent(roomCode)}/roll`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  })
  // 409 = the roll already resolved (double-click, or the server-side
  // timeout beat the click) — not an error worth surfacing.
  if (!response.ok && response.status !== 409) {
    throw new Error(`roll request failed: ${response.status}`)
  }
}
