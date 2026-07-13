// Pure game/client logic shared by components — kept free of React so it's
// unit-testable without a DOM.

import type { DiceRoll, GameSnapshot, RoomEvent, SuggestedAction } from './types'

// Suggestions tagged for another character are theirs, not ours — showing
// them only invites actions the GM will refuse.
export function suggestionsFor(suggestions: SuggestedAction[], playerName: string): string[] {
  return suggestions
    .map((s) => (typeof s === 'string' ? { text: s, character: null } : s))
    .filter((s) => !s.character || s.character === playerName)
    .map((s) => s.text)
}

/** Reconciles an SSE event that was buffered while the snapshot was being
 * fetched: false = the snapshot already reflects it, don't replay. */
export function shouldReplayBufferedEvent(event: RoomEvent, snapshot: GameSnapshot): boolean {
  // Chunks/tool calls from a turn that was already mid-flight when the
  // snapshot was taken are unanchored fragments — drop them; turn_complete
  // carries the full narrative, so nothing is lost.
  if (
    snapshot.turn_in_progress &&
    (event.type === 'narrative_chunk' || event.type === 'tool_call')
  ) {
    return false
  }
  // Log rows the snapshot already includes.
  if (event.type === 'turn_complete' && event.log_id <= snapshot.last_log_id) return false
  // A buffered turn_started for a turn that FINISHED before the snapshot
  // was taken — its player bubble is already a log row.
  if (event.type === 'turn_started' && !snapshot.turn_in_progress) return false
  if (event.type === 'player_joined' && snapshot.players.some((p) => p.name === event.name))
    return false
  // Same dedupe for departures — the snapshot already reflects them.
  if (event.type === 'player_left' && !snapshot.players.some((p) => p.name === event.name))
    return false
  return true
}

export function sidesOf(expression: string): number {
  return Number(/d(\d+)/i.exec(expression)?.[1] ?? 20)
}

export function breakdown(result: DiceRoll): string {
  const mod =
    result.modifier > 0 ? ` + ${result.modifier}` : result.modifier < 0 ? ` − ${-result.modifier}` : ''
  // A single unmodified die needs no arithmetic shown.
  if (result.rolls.length === 1 && !mod) return result.expression
  return `${result.expression}: ${result.rolls.join(' + ')}${mod} = ${result.total}`
}
