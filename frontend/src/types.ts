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
}

export type TurnEvent = ToolCallEvent | NarrativeChunkEvent | TurnCompleteEvent
