import { useEffect, useRef, useState } from 'react'
import { NarrativeStream, type LogEntry } from './components/NarrativeStream'
import { AgentActivityPanel, type ToolActivity } from './components/AgentActivityPanel'
import { NpcRoster } from './components/NpcRoster'
import { ActionChips } from './components/ActionChips'
import { PlayerInput } from './components/PlayerInput'
import { streamTurn } from './api/turn'
import type { StructuredResponse } from './types'

const PLAYER_ID = 'p1'

type WorldState = Pick<
  StructuredResponse,
  'location' | 'exits' | 'visible_npcs' | 'suggested_actions'
>

function App() {
  const [log, setLog] = useState<LogEntry[]>([])
  const [streamingText, setStreamingText] = useState('')
  const [activity, setActivity] = useState<ToolActivity[]>([])
  const [state, setState] = useState<WorldState>({
    location: '',
    exits: {},
    visible_npcs: [],
    suggested_actions: [],
  })
  const [isStreaming, setIsStreaming] = useState(false)
  const started = useRef(false)

  async function takeTurn(message: string, logPlayerAction: boolean) {
    setIsStreaming(true)
    setActivity([])
    setStreamingText('')
    if (logPlayerAction) {
      setLog((prev) => [...prev, { role: 'player', text: message }])
    }

    try {
      await streamTurn(PLAYER_ID, message, (event) => {
        if (event.type === 'tool_call') {
          setActivity((prev) => {
            if (event.status === 'done') {
              // Mark the most recent unmatched "running" call for this tool
              // as done, in case the same tool is called more than once.
              const idx = [...prev]
                .reverse()
                .findIndex((a) => a.tool === event.tool && a.status === 'running')
              if (idx === -1) return [...prev, { tool: event.tool, status: 'done' }]
              const realIdx = prev.length - 1 - idx
              return prev.map((a, i) => (i === realIdx ? { ...a, status: 'done' } : a))
            }
            return [...prev, { tool: event.tool, status: 'running' }]
          })
        } else if (event.type === 'narrative_chunk') {
          setStreamingText((prev) => prev + event.text)
        } else if (event.type === 'turn_complete') {
          const { response } = event
          setLog((prev) => [...prev, { role: 'narrator', text: response.narrative }])
          setStreamingText('')
          setState({
            location: response.location,
            exits: response.exits,
            visible_npcs: response.visible_npcs,
            suggested_actions: response.suggested_actions,
          })
        }
      })
    } catch (error) {
      console.error('takeTurn failed:', error)
      setLog((prev) => [
        ...prev,
        { role: 'narrator', text: `[error] ${error instanceof Error ? error.message : String(error)}` },
      ])
    } finally {
      setIsStreaming(false)
    }
  }

  useEffect(() => {
    // Zero-setup entry: narrate the opening scene without requiring the
    // player to type first. Guarded against React StrictMode's double-invoke.
    if (started.current) return
    started.current = true
    void takeTurn('Begin the adventure.', false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="h-screen flex flex-col bg-zinc-950">
      <header className="px-6 py-3 border-b border-zinc-800 flex items-center justify-between shrink-0">
        <h1 className="text-lg font-semibold text-zinc-100">AI Dungeoneer</h1>
        <span className="text-sm text-zinc-500">{state.location}</span>
      </header>
      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 flex flex-col overflow-hidden">
          <NarrativeStream log={log} streamingText={streamingText} />
          <NpcRoster npcs={state.visible_npcs} />
          <ActionChips
            exits={state.exits}
            suggestions={state.suggested_actions}
            onSelect={(action) => takeTurn(action, true)}
            disabled={isStreaming}
          />
          <PlayerInput onSubmit={(message) => takeTurn(message, true)} disabled={isStreaming} />
        </div>
        <AgentActivityPanel activity={activity} />
      </div>
    </div>
  )
}

export default App
