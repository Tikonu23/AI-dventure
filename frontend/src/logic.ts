// Pure game/client logic shared by components — kept free of React so it's
// unit-testable without a DOM.

import type { DiceRoll, GameMap, GameSnapshot, RoomEvent, SuggestedAction } from './types'

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
  // Stat changes, milestones, and endings from a finished turn are already
  // baked into the snapshot — replaying them could regress the HUD/dots.
  if (
    (event.type === 'player_stats' || event.type === 'game_over' || event.type === 'milestone') &&
    !snapshot.turn_in_progress
  ) {
    return false
  }
  return true
}

/** CSS background-image value for a world backdrop: raster data URIs (local
 * image model) pass through, SVG text gets encoded. background-image never
 * executes SVG scripts, which is why backdrops render this way. */
export function backdropUrl(backdrop: string): string {
  if (backdrop.startsWith('data:image/')) return `url("${backdrop}")`
  return `url("data:image/svg+xml,${encodeURIComponent(backdrop)}")`
}

// Compass directions map straight onto a grid — worldgen only emits these
// six, and the validator guarantees bidirectional exits, so a BFS walk
// lays the whole visited graph out with no physics library.
const DIRECTION_DELTAS: Record<string, [number, number]> = {
  north: [0, -1],
  south: [0, 1],
  east: [1, 0],
  west: [-1, 0],
  up: [1, -1],
  down: [-1, 1],
}

export interface MapLayout {
  nodes: { id: string; name: string; description: string; x: number; y: number }[]
  // vertical = an up/down passage — the renderer marks these with a glyph.
  links: { x1: number; y1: number; x2: number; y2: number; vertical: boolean }[]
  // Doors into the dark: drawn a half-step out from their room.
  stubs: { x: number; y: number }[]
}

export function layoutMap(map: GameMap): MapLayout {
  const positions = new Map<string, [number, number]>()
  const occupied = new Set<string>()
  const cellKey = (x: number, y: number) => `${x},${y}`

  const place = (id: string, x: number, y: number) => {
    // Two paths can imply the same cell for different rooms (grid maps of
    // non-planar graphs do that) — nudge outward to the nearest free cell.
    let [cx, cy] = [x, y]
    for (let ring = 1; occupied.has(cellKey(cx, cy)); ring++) {
      cx = x + ring
    }
    positions.set(id, [cx, cy])
    occupied.add(cellKey(cx, cy))
  }

  const byId = new Map(map.rooms.map((r) => [r.id, r]))
  const neighbors = new Map<string, { to: string; direction: string }[]>()
  for (const e of map.edges) {
    if (!neighbors.has(e.from)) neighbors.set(e.from, [])
    neighbors.get(e.from)!.push({ to: e.to, direction: e.direction })
  }

  // BFS from a deterministic seed; travel implies connectivity, but any
  // stragglers get parked in a fresh column at the end.
  const seedOrder = [...map.rooms].sort((a, b) => a.id.localeCompare(b.id))
  for (const seed of seedOrder) {
    if (positions.has(seed.id)) continue
    place(seed.id, positions.size === 0 ? 0 : Math.max(...[...positions.values()].map(([x]) => x)) + 2, 0)
    const queue = [seed.id]
    while (queue.length > 0) {
      const current = queue.shift()!
      const [cx, cy] = positions.get(current)!
      for (const { to, direction } of neighbors.get(current) ?? []) {
        if (positions.has(to) || !byId.has(to)) continue
        const [dx, dy] = DIRECTION_DELTAS[direction] ?? [1, 1]
        place(to, cx + dx, cy + dy)
        queue.push(to)
      }
    }
  }

  const nodes = map.rooms.map((room) => {
    const [x, y] = positions.get(room.id)!
    return { id: room.id, name: room.name, description: room.description, x, y }
  })
  const links: MapLayout['links'] = []
  const seen = new Set<string>()
  for (const e of map.edges) {
    // Bidirectional exits arrive as two rows — draw each pair once.
    const key = [e.from, e.to].sort().join('|')
    if (seen.has(key)) continue
    seen.add(key)
    const [x1, y1] = positions.get(e.from)!
    const [x2, y2] = positions.get(e.to)!
    links.push({ x1, y1, x2, y2, vertical: e.direction === 'up' || e.direction === 'down' })
  }
  const stubs = map.stubs.map((s) => {
    const [x, y] = positions.get(s.from)!
    const [dx, dy] = DIRECTION_DELTAS[s.direction] ?? [1, 1]
    return { x: x + dx * 0.55, y: y + dy * 0.55 }
  })
  return { nodes, links, stubs }
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
