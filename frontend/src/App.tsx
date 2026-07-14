import { useCallback, useEffect, useRef, useState } from 'react'
import { NarrativeStream } from './components/NarrativeStream'
import { AgentActivityPanel, type ToolActivity } from './components/AgentActivityPanel'
import { NpcRoster } from './components/NpcRoster'
import { ActionChips } from './components/ActionChips'
import { PlayerInput } from './components/PlayerInput'
import { JoinScreen } from './components/JoinScreen'
import { DiceRollPrompt } from './components/DiceRollPrompt'
import { PartyHud } from './components/PartyHud'
import { StatOrb } from './components/StatOrb'
import { TitleMenu } from './components/TitleMenu'
import { postRoll, postTurn, TurnRejectedError } from './api/turn'
import { fetchGameState, leaveGame, SessionInvalidError } from './api/games'
import { subscribeRoom } from './api/events'
import { backdropUrl, shouldReplayBufferedEvent, suggestionsFor } from './logic'
import { MapPanel } from './components/MapPanel'
import type {
  GameMap,
  LogEntry,
  PartyMember,
  RoomEvent,
  Session,
  StructuredResponse,
} from './types'

const EMPTY_MAP: GameMap = { rooms: [], edges: [], stubs: [] }

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
  const [party, setParty] = useState<PartyMember[]>([])
  const [status, setStatus] = useState<'active' | 'won' | 'lost'>('active')
  const [worldBackdrop, setWorldBackdrop] = useState<string | null>(null)
  const [gameMap, setGameMap] = useState<GameMap>(EMPTY_MAP)
  const [milestones, setMilestones] = useState({ done: 0, total: 0 })
  const [mapOpen, setMapOpen] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [isHydrating, setIsHydrating] = useState(true)
  const [actor, setActor] = useState<string | null>(null)
  const [pendingRoll, setPendingRoll] = useState<string | null>(null)
  // Remount key so a second roll in the same turn starts the widget fresh
  // (clicked is its internal state).
  const [rollSeq, setRollSeq] = useState(0)
  // Synchronous mirror of streamingText — dice_result must read-and-cut the
  // accumulated text in one event, which state alone can't do.
  const streamRef = useRef('')
  // Whether this turn's narrative was already committed in segments around
  // roll boxes — turn_complete must then keep the split instead of
  // re-appending the full narrative.
  const rolledRef = useRef(false)
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
      streamRef.current = ''
      rolledRef.current = false
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
      streamRef.current += event.text
      setStreamingText((prev) => prev + event.text)
    } else if (event.type === 'dice_pending') {
      setPendingRoll(event.expression)
      setRollSeq((seq) => seq + 1)
    } else if (event.type === 'dice_result') {
      // Anchor the roll where it happened: commit the narrative streamed so
      // far as its own entry, drop the roll box after it, and stream what
      // follows below. The box does its own tumble-then-settle on mount.
      setPendingRoll(null)
      rolledRef.current = true
      const segment = streamRef.current.trim()
      streamRef.current = ''
      setStreamingText('')
      setLog((prev) => [
        ...prev,
        ...(segment ? [{ role: 'narrator', text: segment } as LogEntry] : []),
        { role: 'roll', text: `${event.expression} = ${event.total}`, roll: event, animate: true },
      ])
    } else if (event.type === 'turn_complete') {
      const { response } = event
      if (rolledRef.current) {
        // Narrative was committed in segments around roll boxes — append
        // only the tail, or the boxes would be buried under a full repeat.
        const tail = streamRef.current.trim()
        if (tail) setLog((prev) => [...prev, { role: 'narrator', text: tail }])
      } else {
        setLog((prev) => [...prev, { role: 'narrator', text: response.narrative }])
      }
      rolledRef.current = false
      streamRef.current = ''
      setStreamingText('')
      setIsStreaming(false)
      setActor(null)
      setPendingRoll(null)
      setState({
        location: response.location,
        exits: response.exits,
        visible_npcs: response.visible_npcs,
        suggested_actions: response.suggested_actions,
      })
      // The party moved — pull fresh map/milestones only (a full snapshot
      // re-apply would clobber the live log).
      if (response.world_updates.some((u) => u.type === 'location_change')) {
        void fetchGameState(session.roomCode, session.playerToken)
          .then((snapshot) => {
            setGameMap(snapshot.map)
            setMilestones(snapshot.milestones)
          })
          .catch(() => {})
      }
    } else if (event.type === 'player_joined') {
      setLog((prev) => [...prev, { role: 'system', text: `${event.name} joins the party.` }])
      setParty((prev) =>
        prev.some((p) => p.name === event.name)
          ? prev
          : [
              ...prev,
              // Fresh joiners start at full pools; the next snapshot or
              // player_stats event corrects if this client is behind.
              { name: event.name, description: '', hp: 100, max_hp: 100, mana: 100, max_mana: 100 },
            ],
      )
    } else if (event.type === 'player_left') {
      setLog((prev) => [...prev, { role: 'system', text: `${event.name} leaves the party.` }])
      setParty((prev) => prev.filter((p) => p.name !== event.name))
    } else if (event.type === 'player_stats') {
      setParty((prev) =>
        prev.map((p) =>
          p.name === event.player
            ? { ...p, hp: event.hp, max_hp: event.max_hp, mana: event.mana, max_mana: event.max_mana }
            : p,
        ),
      )
    } else if (event.type === 'game_over') {
      setStatus(event.outcome)
    } else if (event.type === 'milestone') {
      setMilestones({ done: event.done, total: event.total })
    } else if (event.type === 'turn_error') {
      setLog((prev) => [
        ...prev,
        { role: 'system', text: 'The telling faltered — the turn was lost. Try again.' },
      ])
      setIsStreaming(false)
      setActor(null)
      setPendingRoll(null)
      streamRef.current = ''
      rolledRef.current = false
    }
  }, [session])

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
      document.title = `${snapshot.world_title} — AI-dventure`
      setLog(snapshot.log)
      setParty(snapshot.players)
      setStatus(snapshot.status)
      setWorldBackdrop(snapshot.world_backdrop)
      setGameMap(snapshot.map)
      setMilestones(snapshot.milestones)
      setState({
        location: snapshot.location,
        exits: snapshot.exits,
        visible_npcs: snapshot.visible_npcs,
        suggested_actions: snapshot.suggested_actions,
      })
      setIsStreaming(snapshot.turn_in_progress)
      setActor(snapshot.actor)
      setPendingRoll(snapshot.pending_roll)
      setStreamingText('')
      streamRef.current = ''
      rolledRef.current = false
      setActivity([])

      // Rules for what replays live in logic.ts (unit-tested there).
      for (const event of buffered ?? []) {
        if (shouldReplayBufferedEvent(event, snapshot)) handleEvent(event)
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

  // ponytail: matched by name, same caveat as everywhere else in this file.
  const me = party.find((p) => p.name === session.playerName)

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
    // dvh, not vh: 100vh overshoots the visible area on mobile (URL bar),
    // pushing the input below the fold
    // No bg here — the patterned body backdrop (index.css) shows through
    <div className="h-dvh flex flex-col">
      {/* The world's own scene, above the lattice, below the UI. The SVGs
          are near-black already, so 30% still leaves text fully readable. */}
      {worldBackdrop && (
        <div
          aria-hidden
          className="fixed inset-0 -z-10 bg-cover bg-center pointer-events-none"
          style={{ backgroundImage: backdropUrl(worldBackdrop), opacity: 0.45 }}
        />
      )}
      <header className="px-4 sm:px-6 py-3 sm:py-4 border-b border-zinc-800 flex items-center justify-between gap-2 shrink-0">
        {/* Title, room chip, and Leave are rigid; the location pill is the
            one flexible element — it truncates on narrow screens instead of
            letting the groups overlap each other. */}
        <div className="flex items-center gap-2 sm:gap-4 shrink-0 min-w-0">
          <TitleMenu />
          <button
            onClick={copyInviteLink}
            title="Copy invite link — share it so others can join"
            className="shrink-0 text-xs font-mono tracking-widest text-violet-300 border border-violet-500/30 bg-violet-500/10 rounded-full px-3 py-1 hover:bg-violet-500/20 whitespace-nowrap"
          >
            {copied ? 'Copied!' : `Room ${session.roomCode}`}
          </button>
          {party.length > 0 && (
            <span className="hidden md:inline text-xs text-zinc-500 truncate">
              {party.map((p) => p.name).join(' · ')}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 min-w-0">
          {milestones.total > 0 && (
            <span
              className="shrink-0 text-[10px] tracking-[0.2em] text-violet-300/90"
              title={`Journey: ${milestones.done} of ${milestones.total} milestones`}
            >
              {'◆'.repeat(milestones.done)}
              {'◇'.repeat(milestones.total - milestones.done)}
            </span>
          )}
          {state.location && (
            <button
              type="button"
              onClick={() => setMapOpen(true)}
              title="Show the map"
              className="min-w-0 text-xs uppercase tracking-wider text-zinc-500 border border-zinc-800 rounded-full px-3 py-1 truncate hover:text-zinc-300 hover:border-zinc-600"
            >
              {state.location}
            </button>
          )}
          <button
            onClick={() => {
              if (!window.confirm('Leave this game? Your character departs the party.')) return
              // Fire-and-forget: even if the server call fails, this browser
              // is done with the room — clear the session either way.
              void leaveGame(session.roomCode, session.playerToken).catch(() => {})
              onSessionInvalid()
            }}
            title="Leave this game — you can start or join another"
            className="shrink-0 text-xs text-zinc-500 border border-zinc-800 rounded-full px-3 py-1 hover:text-red-300 hover:border-red-500/40 whitespace-nowrap"
          >
            Leave
          </button>
        </div>
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
            {/* Teammates only — your own vitals are the orbs by the input. */}
            <PartyHud party={party.filter((p) => p.name !== session.playerName)} />
            <NpcRoster npcs={state.visible_npcs} />
            <ActionChips
              exits={state.exits}
              suggestions={suggestionsFor(state.suggested_actions, session.playerName)}
              onSelect={(action) => takeTurn(action, true)}
              disabled={isStreaming || isHydrating || status !== 'active'}
            />
            {status !== 'active' ? (
              // Epilogue: the story is over — input is gone, not just off.
              <div className="px-4 sm:px-6 py-4 text-center">
                <p
                  className={`text-sm font-semibold uppercase tracking-widest ${
                    status === 'won' ? 'text-amber-300' : 'text-rose-400'
                  }`}
                >
                  {status === 'won' ? 'The tale is told — victory.' : '☠ The party has fallen.'}
                </p>
                <p className="mt-1 text-xs text-zinc-500">
                  This story has ended. Leave to begin another.
                </p>
              </div>
            ) : (
              <>
                {pendingRoll !== null && (
                  <DiceRollPrompt
                    key={rollSeq}
                    expression={pendingRoll}
                    // ponytail: matched by name — player names aren't guaranteed
                    // unique in a room; switch to actor_id if that ever bites.
                    canRoll={actor === session.playerName}
                    actor={actor}
                    onRoll={() => void postRoll(session.roomCode, session.playerToken)}
                  />
                )}
                {/* Diablo-style vitals flank the input: blood left, mana right. */}
                <div className="flex items-center gap-1 sm:gap-2 px-2 sm:px-4 py-1 border-t border-zinc-800">
                  {me && <StatOrb kind="hp" label="Health" value={me.hp} max={me.max_hp} />}
                  <PlayerInput
                    onSubmit={(message) => takeTurn(message, true)}
                    disabled={isStreaming || isHydrating}
                  />
                  {me && <StatOrb kind="mana" label="Mana" value={me.mana} max={me.max_mana} />}
                </div>
              </>
            )}
          </div>
        </div>
        <AgentActivityPanel activity={activity} map={gameMap} currentLocation={state.location} />
      </div>
      {/* Map overlay — the phone's path to the map (pill tap), works anywhere. */}
      {mapOpen && (
        <div
          className="fixed inset-0 z-30 flex items-center justify-center bg-black/60 px-4"
          onMouseDown={() => setMapOpen(false)}
        >
          <div
            onMouseDown={(e) => e.stopPropagation()}
            className="w-full max-w-md rounded-xl border border-zinc-700 bg-zinc-900 p-4"
          >
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-zinc-100">Map</h2>
              <button
                type="button"
                onClick={() => setMapOpen(false)}
                className="text-zinc-500 hover:text-zinc-200 text-lg leading-none"
                title="Close"
              >
                ×
              </button>
            </div>
            <MapPanel map={gameMap} currentName={state.location} />
          </div>
        </div>
      )}
    </div>
  )
}

export default App
