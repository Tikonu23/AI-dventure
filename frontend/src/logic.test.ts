import { describe, expect, it } from 'vitest'
import {
  backdropUrl,
  breakdown,
  layoutMap,
  shouldReplayBufferedEvent,
  sidesOf,
  suggestionsFor,
} from './logic'
import type { GameSnapshot, RoomEvent } from './types'

describe('suggestionsFor', () => {
  it('keeps untargeted and own suggestions, hides other characters’', () => {
    const suggestions = [
      { text: 'Look around', character: null },
      { text: 'Read the runes', character: 'Mira' },
      { text: 'Break the door', character: 'Thorin' },
    ]
    expect(suggestionsFor(suggestions, 'Thorin')).toEqual(['Look around', 'Break the door'])
  })

  it('treats bare strings from old games as for-anyone', () => {
    expect(suggestionsFor(['Look around'], 'Thorin')).toEqual(['Look around'])
  })
})

function snapshot(overrides: Partial<GameSnapshot> = {}): GameSnapshot {
  return {
    game_id: 'ROOM1',
    world_title: 'T',
    world_backdrop: null,
    players: [
      { name: 'Thorin', description: 'a dwarf', hp: 100, max_hp: 100, mana: 100, max_mana: 100 },
    ],
    status: 'active',
    log: [],
    last_log_id: 10,
    location: 'Gate',
    exits: {},
    visible_npcs: [],
    suggested_actions: [],
    turn_in_progress: false,
    actor: null,
    pending_roll: null,
    map: { rooms: [], edges: [], stubs: [] },
    milestones: { done: 0, total: 0 },
    ...overrides,
  }
}

describe('shouldReplayBufferedEvent', () => {
  it('drops mid-flight fragments while a turn is in progress', () => {
    const snap = snapshot({ turn_in_progress: true })
    expect(
      shouldReplayBufferedEvent({ type: 'narrative_chunk', text: 'x' }, snap),
    ).toBe(false)
    expect(
      shouldReplayBufferedEvent({ type: 'tool_call', tool: 'roll', status: 'running' }, snap),
    ).toBe(false)
  })

  it('replays fragments when no turn is in flight', () => {
    expect(
      shouldReplayBufferedEvent({ type: 'narrative_chunk', text: 'x' }, snapshot()),
    ).toBe(true)
  })

  it('drops turn_complete rows the snapshot already includes', () => {
    const complete = {
      type: 'turn_complete',
      response: {
        narrative: '',
        location: '',
        exits: {},
        visible_npcs: [],
        suggested_actions: [],
        world_updates: [],
      },
      actor: 'Thorin',
      log_id: 10,
    } satisfies RoomEvent
    expect(shouldReplayBufferedEvent(complete, snapshot({ last_log_id: 10 }))).toBe(false)
    expect(shouldReplayBufferedEvent({ ...complete, log_id: 11 }, snapshot())).toBe(true)
  })

  it('drops a turn_started whose turn already finished before the snapshot', () => {
    const started = {
      type: 'turn_started',
      actor: 'Thorin',
      actor_id: 'p1',
      message: 'I strike.',
      logged: true,
    } satisfies RoomEvent
    expect(shouldReplayBufferedEvent(started, snapshot({ turn_in_progress: false }))).toBe(false)
    expect(shouldReplayBufferedEvent(started, snapshot({ turn_in_progress: true }))).toBe(true)
  })

  it('drops milestone events from finished turns', () => {
    const milestone = { type: 'milestone', done: 1, total: 3 } satisfies RoomEvent
    expect(shouldReplayBufferedEvent(milestone, snapshot({ turn_in_progress: false }))).toBe(false)
    expect(shouldReplayBufferedEvent(milestone, snapshot({ turn_in_progress: true }))).toBe(true)
  })

  it('drops stats/game_over from finished turns (snapshot already has them)', () => {
    const stats = {
      type: 'player_stats',
      player: 'Thorin',
      hp: 50,
      max_hp: 100,
      mana: 100,
      max_mana: 100,
      dead: false,
      game_lost: false,
    } satisfies RoomEvent
    const over = { type: 'game_over', outcome: 'lost' } satisfies RoomEvent
    expect(shouldReplayBufferedEvent(stats, snapshot({ turn_in_progress: false }))).toBe(false)
    expect(shouldReplayBufferedEvent(over, snapshot({ turn_in_progress: false }))).toBe(false)
    expect(shouldReplayBufferedEvent(stats, snapshot({ turn_in_progress: true }))).toBe(true)
    expect(shouldReplayBufferedEvent(over, snapshot({ turn_in_progress: true }))).toBe(true)
  })

  it('dedupes joins and leaves against the snapshot roster', () => {
    const snap = snapshot()
    expect(shouldReplayBufferedEvent({ type: 'player_joined', name: 'Thorin' }, snap)).toBe(false)
    expect(shouldReplayBufferedEvent({ type: 'player_joined', name: 'Mira' }, snap)).toBe(true)
    expect(shouldReplayBufferedEvent({ type: 'player_left', name: 'Mira' }, snap)).toBe(false)
    expect(shouldReplayBufferedEvent({ type: 'player_left', name: 'Thorin' }, snap)).toBe(true)
  })
})

describe('backdropUrl', () => {
  it('passes raster data URIs through verbatim', () => {
    expect(backdropUrl('data:image/png;base64,AAAA')).toBe('url("data:image/png;base64,AAAA")')
  })

  it('encodes SVG text into a data URI', () => {
    expect(backdropUrl('<svg fill="#111"/>')).toBe(
      `url("data:image/svg+xml,${encodeURIComponent('<svg fill="#111"/>')}")`,
    )
  })
})

describe('layoutMap', () => {
  it('lays rooms out on a compass grid with stubs a half-step out', () => {
    const layout = layoutMap({
      rooms: [
        { id: 'a', name: 'Gate', description: 'a gate' },
        { id: 'b', name: 'Crypt', description: 'a crypt' },
      ],
      edges: [
        { from: 'a', direction: 'north', to: 'b' },
        { from: 'b', direction: 'south', to: 'a' },
      ],
      stubs: [{ from: 'b', direction: 'east' }],
    })
    const gate = layout.nodes.find((n) => n.id === 'a')!
    const crypt = layout.nodes.find((n) => n.id === 'b')!
    expect(crypt.y).toBe(gate.y - 1)
    expect(crypt.x).toBe(gate.x)
    // Bidirectional pair drawn as a single link, not a vertical one.
    expect(layout.links).toHaveLength(1)
    expect(layout.links[0].vertical).toBe(false)
    expect(layout.stubs[0]).toEqual({ x: crypt.x + 0.55, y: crypt.y })
  })

  it('marks up/down passages as vertical links', () => {
    const layout = layoutMap({
      rooms: [
        { id: 'a', name: 'Ossuary', description: 'bones' },
        { id: 'b', name: 'Chapel', description: 'drowned' },
      ],
      edges: [
        { from: 'a', direction: 'down', to: 'b' },
        { from: 'b', direction: 'up', to: 'a' },
      ],
      stubs: [],
    })
    expect(layout.links).toHaveLength(1)
    expect(layout.links[0].vertical).toBe(true)
  })

  it('nudges colliding rooms instead of stacking them', () => {
    // b is north of a; c is west of b AND north of d, where d is west of a —
    // both paths put c at (-1,-1)... build a simpler direct collision:
    // two different rooms both claim the cell north of the seed.
    const layout = layoutMap({
      rooms: [
        { id: 'a', name: 'A', description: '' },
        { id: 'b', name: 'B', description: '' },
        { id: 'c', name: 'C', description: '' },
        { id: 'd', name: 'D', description: '' },
      ],
      edges: [
        { from: 'a', direction: 'north', to: 'b' },
        { from: 'a', direction: 'up', to: 'c' },
        { from: 'c', direction: 'west', to: 'd' },
      ],
      stubs: [],
    })
    // d lands where b already is ((0,-1) via up(1,-1)+west(-1,0)) — nudged.
    const cells = layout.nodes.map((n) => `${n.x},${n.y}`)
    expect(new Set(cells).size).toBe(4)
  })
})

describe('dice helpers', () => {
  it('reads the die size from the expression, defaulting to d20', () => {
    expect(sidesOf('2d6+3')).toBe(6)
    expect(sidesOf('1d100')).toBe(100)
    expect(sidesOf('garbage')).toBe(20)
  })

  it('formats a single unmodified die as just the expression', () => {
    expect(breakdown({ expression: '1d20', rolls: [17], modifier: 0, total: 17 })).toBe('1d20')
  })

  it('shows the arithmetic for multi-die and modified rolls', () => {
    expect(breakdown({ expression: '2d6+3', rolls: [4, 5], modifier: 3, total: 12 })).toBe(
      '2d6+3: 4 + 5 + 3 = 12',
    )
    expect(breakdown({ expression: '1d20-2', rolls: [9], modifier: -2, total: 7 })).toBe(
      '1d20-2: 9 − 2 = 7',
    )
  })
})
