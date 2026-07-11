export interface WorldUpdate {
  type: string
  [key: string]: unknown
}

export interface StructuredResponse {
  narrative: string
  location: string
  exits: Record<string, string>
  visible_npcs: string[]
  suggested_actions: string[]
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

export interface TurnErrorEvent {
  type: 'turn_error'
}

/** Everything the per-room SSE stream can carry. */
export type RoomEvent =
  | ToolCallEvent
  | NarrativeChunkEvent
  | TurnCompleteEvent
  | TurnStartedEvent
  | PlayerJoinedEvent
  | TurnErrorEvent

export interface LogEntry {
  role: 'player' | 'narrator' | 'system'
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
  players: PartyMember[]
  log: LogEntry[]
  last_log_id: number
  location: string
  exits: Record<string, string>
  visible_npcs: string[]
  suggested_actions: string[]
  turn_in_progress: boolean
  actor: string | null
}
