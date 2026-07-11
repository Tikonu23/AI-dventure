import type { RoomEvent } from '../types'

/**
 * Subscribe to a room's event stream. Native EventSource works here (unlike
 * the old POST /turn stream) because it's a plain GET — and it brings free
 * auto-reconnect. `onReconnect` fires when the connection re-opens after a
 * drop, so the caller can refetch the snapshot and fill whatever was missed
 * while offline.
 *
 * Returns an unsubscribe function.
 */
export function subscribeRoom(
  roomCode: string,
  onEvent: (event: RoomEvent) => void,
  onReconnect: () => void,
): () => void {
  const source = new EventSource(`/api/games/${encodeURIComponent(roomCode)}/events`)
  let hadError = false

  source.onmessage = (e) => {
    onEvent(JSON.parse(e.data) as RoomEvent)
  }
  source.onerror = () => {
    // EventSource retries on its own; just remember there was a gap.
    hadError = true
  }
  source.onopen = () => {
    if (hadError) {
      hadError = false
      onReconnect()
    }
  }

  return () => source.close()
}
