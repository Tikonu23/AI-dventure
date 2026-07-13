export interface WorldUpdate {
  type: string
  [key: string]: unknown
}

/** A suggested next action; `character` names the only party member it's
 * meant for (null = anyone). Bare strings are pre-targeting turns from
 * old games — treated as for-anyone. */
export type SuggestedAction = string | { text: string; character: string | null }

export interface StructuredResponse {
  narrative: string
  location: string
  exits: Record<string, string>
  visible_npcs: string[]
  suggested_actions: SuggestedAction[]
  world_updates: WorldUpdate[]
}

export interface ToolCallEvent {
  type: 'tool_call'
  tool: string
  status: 'running' | 'done'
}

export interface NarrativeChunkEvent {
  type: 'narrative_chunk'
  text: string
}

export interface TurnCompleteEvent {
  type: 'turn_complete'
  response: StructuredResponse
  actor: string
  // Last game_log row this turn wrote — lets a reconnecting client drop a
  // turn_complete it already has in its snapshot.
  log_id: number
}

export interface TurnStartedEvent {
  type: 'turn_started'
  actor: string
  actor_id: string
  // The action text, so every other client can render the actor's bubble
  // live. `logged` mirrors log_player_action — false for stage directions
  // like the auto-sent opening, which get no bubble anywhere.
  message: string
  logged: boolean
}

export interface PlayerJoinedEvent {
  type: 'player_joined'
  name: string
}

export interface PlayerLeftEvent {
  type: 'player_left'
  name: string
}

export interface TurnErrorEvent {
  type: 'turn_error'
}

/** The turn is paused server-side until a player clicks the die. */
export interface DicePendingEvent {
  type: 'dice_pending'
  expression: string
}

/** A resolved roll — as broadcast live and as persisted in game_log rows. */
export interface DiceRoll {
  expression: string
  rolls: number[]
  modifier: number
  total: number
}

export interface DiceResultEvent extends DiceRoll {
  type: 'dice_result'
}

/** Everything the per-room SSE stream can carry. */
export type RoomEvent =
  | ToolCallEvent
  | NarrativeChunkEvent
  | TurnCompleteEvent
  | TurnStartedEvent
  | PlayerJoinedEvent
  | PlayerLeftEvent
  | TurnErrorEvent
  | DicePendingEvent
  | DiceResultEvent

export interface LogEntry {
  role: 'player' | 'narrator' | 'system' | 'roll'
  roll?: DiceRoll
  // Client-only: set on rolls that just resolved so their box tumbles in;
  // rows loaded from the snapshot render already settled.
  animate?: boolean
  // Set for role 'player' — whose bubble this is. The id (not the name) is
  // what decides mine-vs-teammate styling: names can collide within a room.
  // Snake case to match the backend rows verbatim, like the other
  // API-shaped fields here.
  player_id?: string | null
  player_name?: string | null
  text: string
}

export interface PartyMember {
  name: string
  description: string
}

/** A ready pool world offered on the new-game menu. */
export interface World {
  id: string
  title: string
  concept: string
  // Claude-drawn SVG scene; null = no art for this world.
  backdrop_svg: string | null
}

/** This browser's identity in one room, persisted to localStorage. */
export interface Session {
  roomCode: string
  playerId: string
  playerToken: string
  playerName: string
}

/** GET /games/{id}/state — everything needed to (re)hydrate the screen. */
export interface GameSnapshot {
  game_id: string
  world_title: string
  world_backdrop: string | null
  players: PartyMember[]
  log: LogEntry[]
  last_log_id: number
  location: string
  exits: Record<string, string>
  visible_npcs: string[]
  suggested_actions: SuggestedAction[]
  turn_in_progress: boolean
  actor: string | null
  // Dice expression a mid-flight turn is blocked on, for reconnects.
  pending_roll: string | null
}
