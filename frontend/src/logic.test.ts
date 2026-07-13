import { describe, expect, it } from 'vitest'
import { breakdown, shouldReplayBufferedEvent, sidesOf, suggestionsFor } from './logic'
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
    players: [{ name: 'Thorin', description: 'a dwarf' }],
    log: [],
    last_log_id: 10,
    location: 'Gate',
    exits: {},
    visible_npcs: [],
    suggested_actions: [],
    turn_in_progress: false,
    actor: null,
    pending_roll: null,
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

  it('dedupes joins and leaves against the snapshot roster', () => {
    const snap = snapshot()
    expect(shouldReplayBufferedEvent({ type: 'player_joined', name: 'Thorin' }, snap)).toBe(false)
    expect(shouldReplayBufferedEvent({ type: 'player_joined', name: 'Mira' }, snap)).toBe(true)
    expect(shouldReplayBufferedEvent({ type: 'player_left', name: 'Mira' }, snap)).toBe(false)
    expect(shouldReplayBufferedEvent({ type: 'player_left', name: 'Thorin' }, snap)).toBe(true)
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
