import { useCallback, useEffect, useRef, useState } from 'react'
import { NarrativeStream } from './components/NarrativeStream'
import { AgentActivityPanel, type ToolActivity } from './components/AgentActivityPanel'
import { NpcRoster } from './components/NpcRoster'
import { ActionChips } from './components/ActionChips'
import { PlayerInput } from './components/PlayerInput'
import { JoinScreen } from './components/JoinScreen'
import { postTurn, TurnRejectedError } from './api/turn'
import { fetchGameState, SessionInvalidError } from './api/games'
import { subscribeRoom } from './api/events'
import type { LogEntry, RoomEvent, Session, StructuredResponse } from './types'

const LAST_ROOM_KEY = 'ai-dventure:last-room'
const sessionKey = (roomCode: string) => `ai-dventure:session:${roomCode}`

// The URL is the router: /room/CODE names the room being played, so the
// address bar doubles as the invite link. Sessions are stored per room —
// following a friend's link to another room must not clobber this one.
function roomFromUrl(): string | null {
  const match = window.location.pathname.match(/^\/room\/([A-Za-z0-9]+)\/?$/)
  return match ? match[1].toUpperCase() : null
}

// Pre-URL builds stored a single session under one key — adopt it once.
function migrateLegacySession(): void {
  const raw = localStorage.getItem('ai-dventure:session')
  if (!raw) return
  try {
    const legacy = JSON.parse(raw) as Session
    localStorage.setItem(sessionKey(legacy.roomCode), raw)
    localStorage.setItem(LAST_ROOM_KEY, legacy.roomCode)
  } catch {
    // Unparseable legacy blob — nothing worth keeping.
  }
  localStorage.removeItem('ai-dventure:session')
}

function loadSession(roomCode: string | null): Session | null {
  migrateLegacySession()
  const code = roomCode ?? localStorage.getItem(LAST_ROOM_KEY)
  if (!code) return null
  try {
    const raw = localStorage.getItem(sessionKey(code))
    return raw ? (JSON.parse(raw) as Session) : null
  } catch {
    return null
  }
}

type WorldState = Pick<
  StructuredResponse,
  'location' | 'exits' | 'visible_npcs' | 'suggested_actions'
>

function App() {
  const [session, setSession] = useState<Session | null>(() => loadSession(roomFromUrl()))

  // Keep the address bar pointed at the room being played — replaceState,
  // not pushState: with a single in-app "route" a history stack would only
  // make Back bounce between states that render identically.
  useEffect(() => {
    if (session) {
      window.history.replaceState(null, '', `/room/${session.roomCode}`)
    }
  }, [session])

  if (!session) {
    return (
      <JoinScreen
        // A /room/CODE link without a session lands here — prefill the code.
        initialRoomCode={roomFromUrl() ?? ''}
        onSession={(s) => {
          localStorage.setItem(sessionKey(s.roomCode), JSON.stringify(s))
          localStorage.setItem(LAST_ROOM_KEY, s.roomCode)
          setSession(s)
        }}
      />
    )
  }

  return (
    <Game
      // Key on the room so switching sessions remounts with clean state.
      key={session.roomCode}
      session={session}
      onSessionInvalid={() => {
        localStorage.removeItem(sessionKey(session.roomCode))
        if (localStorage.getItem(LAST_ROOM_KEY) === session.roomCode) {
          localStorage.removeItem(LAST_ROOM_KEY)
        }
        window.history.replaceState(null, '', '/')
        setSession(null)
      }}
    />
  )
}

function Game({
  session,
  onSessionInvalid,
}: {
  session: Session
  onSessionInvalid: () => void
}) {
  const [log, setLog] = useState<LogEntry[]>([])
  const [streamingText, setStreamingText] = useState('')
  const [activity, setActivity] = useState<ToolActivity[]>([])
  const [state, setState] = useState<WorldState>({
    location: '',
    exits: {},
    visible_npcs: [],
    suggested_actions: [],
  })
  const [partyNames, setPartyNames] = useState<string[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [isHydrating, setIsHydrating] = useState(true)
  const [actor, setActor] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  // StrictMode double-invoke guard for the auto-sent opening turn.
  const began = useRef(false)

  const handleEvent = useCallback((event: RoomEvent) => {
    if (event.type === 'turn_started') {
      // Everyone's isStreaming — actor and spectators alike — is driven by
      // this broadcast, not by whose POST it was: one rendering path.
      setIsStreaming(true)
      setActor(event.actor)
      setActivity([])
      setStreamingText('')
      // Teammates' dialog lands here, live. The actor's own client skips it —
      // their bubble was already added optimistically in takeTurn.
      if (event.logged && event.actor_id !== session.playerId) {
        setLog((prev) => [
          ...prev,
          {
            role: 'player',
            player_id: event.actor_id,
            player_name: event.actor,
            text: event.message,
          },
        ])
      }
    } else if (event.type === 'tool_call') {
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
      setIsStreaming(false)
      setActor(null)
      setState({
        location: response.location,
        exits: response.exits,
        visible_npcs: response.visible_npcs,
        suggested_actions: response.suggested_actions,
      })
    } else if (event.type === 'player_joined') {
      setLog((prev) => [...prev, { role: 'system', text: `${event.name} joins the party.` }])
      setPartyNames((prev) => (prev.includes(event.name) ? prev : [...prev, event.name]))
    } else if (event.type === 'turn_error') {
      setLog((prev) => [
        ...prev,
        { role: 'system', text: 'The telling faltered — the turn was lost. Try again.' },
      ])
      setIsStreaming(false)
      setActor(null)
    }
  }, [session.playerId])

  const takeTurn = useCallback(
    async (message: string, logPlayerAction: boolean) => {
      if (logPlayerAction) {
        setLog((prev) => [
          ...prev,
          {
            role: 'player',
            player_id: session.playerId,
            player_name: session.playerName,
            text: message,
          },
        ])
      }
      try {
        await postTurn(session.roomCode, session.playerToken, message, logPlayerAction)
      } catch (error) {
        if (logPlayerAction) {
          // Roll back the optimistic bubble — this action never happened.
          setLog((prev) => prev.slice(0, -1))
        }
        if (error instanceof TurnRejectedError) {
          setNotice(`${error.actor} is already acting — wait for their turn to resolve.`)
          setTimeout(() => setNotice(null), 4000)
        } else {
          console.error('takeTurn failed:', error)
          setLog((prev) => [
            ...prev,
            {
              role: 'system',
              text: `[error] ${error instanceof Error ? error.message : String(error)}`,
            },
          ])
        }
      }
    },
    [session],
  )

  const applySnapshot = useCallback(
    async (buffered?: RoomEvent[]) => {
      const snapshot = await fetchGameState(session.roomCode, session.playerToken)
      document.title = `${snapshot.world_title} — AI Dungeoneer`
      setLog(snapshot.log)
      setPartyNames(snapshot.players.map((p) => p.name))
      setState({
        location: snapshot.location,
        exits: snapshot.exits,
        visible_npcs: snapshot.visible_npcs,
        suggested_actions: snapshot.suggested_actions,
      })
      setIsStreaming(snapshot.turn_in_progress)
      setActor(snapshot.actor)
      setStreamingText('')
      setActivity([])

      for (const event of buffered ?? []) {
        // Chunks/tool calls from a turn that was already mid-flight when the
        // snapshot was taken are unanchored fragments — drop them;
        // turn_complete carries the full narrative, so nothing is lost.
        if (
          snapshot.turn_in_progress &&
          (event.type === 'narrative_chunk' || event.type === 'tool_call')
        ) {
          continue
        }
        // Log rows the snapshot already includes.
        if (event.type === 'turn_complete' && event.log_id <= snapshot.last_log_id) continue
        // A buffered turn_started for a turn that FINISHED before the
        // snapshot was taken — its player bubble is already a log row.
        if (event.type === 'turn_started' && !snapshot.turn_in_progress) continue
        if (event.type === 'player_joined' && snapshot.players.some((p) => p.name === event.name))
          continue
        handleEvent(event)
      }
      return snapshot
    },
    [session, handleEvent],
  )

  useEffect(() => {
    // Subscribe BEFORE fetching the snapshot so no event can fall in the gap
    // between them; events that arrive early are buffered and reconciled
    // against the snapshot.
    let buffer: RoomEvent[] | null = []
    const unsubscribe = subscribeRoom(
      session.roomCode,
      (event) => {
        if (buffer) buffer.push(event)
        else handleEvent(event)
      },
      () => {
        // Reconnected after a drop — refetch to fill whatever was missed.
        void applySnapshot().catch((error) => {
          if (error instanceof SessionInvalidError) onSessionInvalid()
        })
      },
    )

    applySnapshot(buffer)
      .then((snapshot) => {
        buffer = null
        // Fresh game: nothing has been narrated yet — kick off the opening
        // scene without requiring anyone to type. Guarded against React
        // StrictMode's double-invoke.
        if (snapshot.log.length === 0 && !snapshot.turn_in_progress && !began.current) {
          began.current = true
          void takeTurn('Begin the adventure.', false)
        }
      })
      .catch((error) => {
        buffer = null
        if (error instanceof SessionInvalidError) {
          // Game was cleaned up (or the token is stale) — back to the gate.
          onSessionInvalid()
          return
        }
        console.error('hydration failed:', error)
        setLog([
          {
            role: 'system',
            text: `[error] Failed to load the game: ${error instanceof Error ? error.message : String(error)}`,
          },
        ])
      })
      .finally(() => setIsHydrating(false))

    return unsubscribe
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.roomCode])

  function copyInviteLink() {
    // The full URL, not the bare code — friends just paste it and land on
    // the join screen with the room prefilled.
    const link = `${window.location.origin}/room/${session.roomCode}`
    void navigator.clipboard.writeText(link).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <div className="h-screen flex flex-col bg-zinc-950">
      <header className="px-4 sm:px-6 py-3 sm:py-4 border-b border-zinc-800 flex items-center justify-between gap-2 shrink-0">
        {/* min-w-0 so the party-names span truncates instead of wrapping the
            whole header into multiple rows on narrow screens. */}
        <div className="flex items-center gap-2 sm:gap-4 min-w-0">
          <h1 className="text-base sm:text-lg font-semibold tracking-wide text-zinc-100 uppercase whitespace-nowrap">
            AI Dungeoneer
          </h1>
          <button
            onClick={copyInviteLink}
            title="Copy invite link — share it so others can join"
            className="shrink-0 text-xs font-mono tracking-widest text-violet-300 border border-violet-500/30 bg-violet-500/10 rounded-full px-3 py-1 hover:bg-violet-500/20 whitespace-nowrap"
          >
            {copied ? 'Copied!' : `Room ${session.roomCode}`}
          </button>
          {partyNames.length > 0 && (
            <span className="hidden md:inline text-xs text-zinc-500 truncate">
              {partyNames.join(' · ')}
            </span>
          )}
        </div>
        {state.location && (
          <span className="text-xs uppercase tracking-wider text-zinc-500 border border-zinc-800 rounded-full px-3 py-1 whitespace-nowrap truncate">
            {state.location}
          </span>
        )}
      </header>
      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 flex flex-col overflow-hidden">
          <NarrativeStream
            log={log}
            streamingText={streamingText}
            isStreaming={isStreaming || isHydrating}
            actor={actor ?? undefined}
            selfId={session.playerId}
          />
          {/* Shares NarrativeStream's max-w-3xl centering so exits/chips/input
              line up under the text instead of stretching full width. */}
          <div className="w-full max-w-3xl mx-auto">
            {notice && <div className="px-4 sm:px-6 py-1 text-sm text-amber-400">{notice}</div>}
            <NpcRoster npcs={state.visible_npcs} />
            <ActionChips
              exits={state.exits}
              suggestions={state.suggested_actions}
              onSelect={(action) => takeTurn(action, true)}
              disabled={isStreaming || isHydrating}
            />
            <PlayerInput
              onSubmit={(message) => takeTurn(message, true)}
              disabled={isStreaming || isHydrating}
            />
          </div>
        </div>
        <AgentActivityPanel activity={activity} />
      </div>
    </div>
  )
}

export default App
