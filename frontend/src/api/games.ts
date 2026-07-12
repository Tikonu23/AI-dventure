import type { GameSnapshot, World } from '../types'

/** The chosen world got claimed between menu render and click — refetch the
 * menu and let the player pick again. */
export class WorldTakenError extends Error {
  constructor() {
    super('That world was just claimed by another party.')
    this.name = 'WorldTakenError'
  }
}

/** The stored session no longer maps to a live game/player (game cleaned up,
 * or token invalid) — the caller should clear localStorage and return to the
 * join screen rather than retrying. */
export class SessionInvalidError extends Error {
  constructor(status: number) {
    super(`session invalid: ${status}`)
    this.name = 'SessionInvalidError'
  }
}

interface JoinResult {
  game_id?: string
  player_id: string
  player_token: string
  // Sanitized server-side (brackets/newlines stripped, clamped) — store
  // THIS as the session name so it matches what other players see.
  name: string
}

export async function listWorlds(): Promise<World[]> {
  const response = await fetch('/api/worlds')
  if (!response.ok) throw new Error(`worlds request failed: ${response.status}`)
  return (await response.json()) as World[]
}

export async function createGame(
  name: string,
  description: string,
  worldId?: string,
): Promise<Required<JoinResult>> {
  const response = await fetch('/api/games', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description, world_id: worldId ?? null }),
  })
  if (response.status === 409) throw new WorldTakenError()
  if (!response.ok) throw new Error(`create game failed: ${response.status}`)
  return (await response.json()) as Required<JoinResult>
}

export async function joinGame(
  roomCode: string,
  name: string,
  description: string,
): Promise<JoinResult> {
  const response = await fetch(`/api/games/${encodeURIComponent(roomCode)}/join`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description }),
  })
  if (response.status === 404) throw new Error(`No game found with room code "${roomCode}".`)
  if (!response.ok) throw new Error(`join game failed: ${response.status}`)
  return (await response.json()) as JoinResult
}

/** Remove this character from the party. Fire-and-forget on the client —
 * the local session is cleared regardless of the server's answer. */
export async function leaveGame(roomCode: string, token: string): Promise<void> {
  await fetch(`/api/games/${encodeURIComponent(roomCode)}/leave`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  })
}

export async function fetchGameState(roomCode: string, token: string): Promise<GameSnapshot> {
  const response = await fetch(
    `/api/games/${encodeURIComponent(roomCode)}/state?token=${encodeURIComponent(token)}`,
  )
  if (response.status === 404 || response.status === 403) {
    throw new SessionInvalidError(response.status)
  }
  if (!response.ok) throw new Error(`state request failed: ${response.status}`)
  return (await response.json()) as GameSnapshot
}
