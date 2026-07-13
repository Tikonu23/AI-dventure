import { useEffect, useState, type FormEvent } from 'react'
import { createGame, fetchGameState, joinGame, listWorlds, WorldTakenError } from '../api/games'
import {
  deleteCharacter,
  findCharacter,
  loadCharacters,
  saveCharacter,
  type SavedCharacter,
} from '../characters'
import { backdropUrl } from '../logic'
import { TitleMenu } from './TitleMenu'
import type { Session, World } from '../types'

interface Props {
  onSession: (session: Session) => void
  // Prefilled when the player arrived via an invite link (/room/CODE).
  initialRoomCode?: string
}

const inputClasses =
  'w-full rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-3 text-base text-zinc-100 ' +
  'placeholder-zinc-600 focus:outline-none focus:border-violet-400 focus:ring-1 focus:ring-violet-400'

/** Pre-game gate: forge a character, then either join an existing room by
 * code or pick a ready-made world and start a fresh game (which mints a new
 * code to share). */
export function JoinScreen({ onSession, initialRoomCode }: Props) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [roomCode, setRoomCode] = useState(initialRoomCode ?? '')
  const [characters, setCharacters] = useState<SavedCharacter[]>(() => loadCharacters())
  const [worlds, setWorlds] = useState<World[]>([])
  const [worldId, setWorldId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const joining = roomCode.trim().length > 0
  // Empty pool (just after boot, or a burst of creates): no menu, the
  // create button generates a world on demand exactly as before.
  const mustPickWorld = !joining && worlds.length > 0 && worldId === null

  async function refreshWorlds() {
    try {
      setWorlds(await listWorlds())
    } catch {
      // Menu is a nicety — creation still works without it.
      setWorlds([])
    }
  }

  useEffect(() => {
    void refreshWorlds()
  }, [])

  // Adoption pass: characters made before the roster feature live only in
  // per-room sessions + the server. Pull each stored session's character in,
  // if its game still exists — left or cleaned-up games stay gone.
  useEffect(() => {
    async function adoptFromSessions() {
      const sessions: { roomCode: string; playerToken: string; playerName: string }[] = []
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i)
        if (!key?.startsWith('ai-dventure:session:')) continue
        try {
          sessions.push(JSON.parse(localStorage.getItem(key)!))
        } catch {
          // Unparseable session — nothing to adopt.
        }
      }
      let added = false
      for (const session of sessions) {
        if (findCharacter(session.playerName)) continue
        try {
          const snapshot = await fetchGameState(session.roomCode, session.playerToken)
          const me = snapshot.players.find((p) => p.name === session.playerName)
          if (me) {
            saveCharacter({ name: me.name, description: me.description })
            added = true
          }
        } catch {
          // Game gone or token stale — that character is no longer "held".
        }
      }
      if (added) setCharacters(loadCharacters())
    }
    void adoptFromSessions()
  }, [])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmedName = name.trim()
    const trimmedDescription = description.trim()
    if (!trimmedName || !trimmedDescription || busy || mustPickWorld) return

    // Roster names are unique: a different description under a saved name
    // is a new character wearing an old name — make them delete first.
    const saved = findCharacter(trimmedName)
    if (saved && saved.description !== trimmedDescription) {
      setError(
        `You already have a character named ${trimmedName} — select them or delete them first.`,
      )
      return
    }

    setBusy(true)
    setError(null)
    try {
      const code = roomCode.trim().toUpperCase()
      const result = joining
        ? { game_id: code, ...(await joinGame(code, trimmedName, trimmedDescription)) }
        : await createGame(trimmedName, trimmedDescription, worldId ?? undefined)
      if (!saved) {
        // result.name is the server-sanitized form — store what others see.
        saveCharacter({ name: result.name, description: trimmedDescription })
      }
      onSession({
        roomCode: result.game_id,
        playerId: result.player_id,
        playerToken: result.player_token,
        playerName: result.name,
      })
    } catch (err) {
      if (err instanceof WorldTakenError) {
        // Another party grabbed it between render and click — re-offer.
        setWorldId(null)
        void refreshWorlds()
      }
      setError(err instanceof Error ? err.message : String(err))
      setBusy(false)
    }
  }

  return (
    // my-auto instead of items-center: the form can now outgrow a phone
    // screen (3 world cards), and items-center clips overflow at the top.
    <div className="h-dvh flex justify-center px-6 py-6 overflow-y-auto">
      <form onSubmit={handleSubmit} className="w-full max-w-md space-y-4 my-auto">
        <div className="flex justify-center">
          <TitleMenu />
        </div>
        <p className="text-sm text-zinc-500 text-center">
          Forge a character. Your description is your character sheet — the
          world will hold you to it.
        </p>
        {characters.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs uppercase tracking-wider text-zinc-500">Your characters</p>
            <div className="flex flex-wrap gap-2">
              {characters.map((c) => (
                <span
                  key={c.name}
                  className={`inline-flex items-center gap-1.5 rounded-full border pl-3 pr-2 py-1 text-xs ${
                    name === c.name && description === c.description
                      ? 'border-violet-400 bg-violet-500/10 text-violet-200'
                      : 'border-zinc-700 bg-zinc-900 text-zinc-300'
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => {
                      setName(c.name)
                      setDescription(c.description)
                      setError(null)
                    }}
                    className="hover:text-violet-300"
                  >
                    {c.name}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      // Same confirm pattern as Leave — a description is not
                      // recoverable once the roster forgets it.
                      if (!window.confirm(`Delete ${c.name}? Their description is lost with them.`))
                        return
                      deleteCharacter(c.name)
                      setCharacters(loadCharacters())
                    }}
                    title={`Delete ${c.name}`}
                    className="text-zinc-600 hover:text-red-400 leading-none"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          </div>
        )}
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Character name"
          maxLength={30}
          autoFocus
          className={inputClasses}
        />
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Describe your character — e.g. a dwarf warrior with a battleaxe and a grudge"
          maxLength={500}
          rows={3}
          className={`${inputClasses} resize-none`}
        />
        <input
          value={roomCode}
          onChange={(e) => setRoomCode(e.target.value.toUpperCase())}
          placeholder="Room code (leave empty to start a new game)"
          maxLength={5}
          className={`${inputClasses} font-mono tracking-widest`}
        />
        {!joining && worlds.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs uppercase tracking-wider text-zinc-500">Choose your world</p>
            {worlds.map((world) => (
              <button
                key={world.id}
                type="button"
                onClick={() => setWorldId(world.id)}
                className={`relative overflow-hidden w-full text-left rounded-lg border px-4 py-3 ${
                  worldId === world.id
                    ? 'border-violet-400 bg-violet-500/10'
                    : 'border-zinc-700 bg-zinc-900 hover:border-zinc-500'
                }`}
              >
                {world.backdrop_svg && (
                  // The world's own scene as a dimmed card background —
                  // choosing a world should feel like choosing a place. A
                  // gradient scrim in the same stack keeps text readable over
                  // bright raster art (Grok paints lighter than the SVGs).
                  <span
                    aria-hidden
                    className="absolute inset-0 bg-cover bg-center pointer-events-none"
                    style={{
                      backgroundImage: `linear-gradient(to right, rgba(11,11,15,0.68), rgba(11,11,15,0.2)), ${backdropUrl(world.backdrop_svg)}`,
                    }}
                  />
                )}
                {/* Dark text halos, not a heavier scrim: keeps the art bright
                    while staying readable even where it matches the font color. */}
                <span className="relative block text-sm font-medium text-zinc-100 [text-shadow:0_0_6px_rgba(0,0,0,0.95),0_1px_2px_rgba(0,0,0,0.95)]">
                  {world.title}
                </span>
                {/* No `block` here — line-clamp needs its own -webkit-box display. */}
                <span className="relative mt-1 text-xs text-zinc-300 line-clamp-3 [text-shadow:0_0_5px_rgba(0,0,0,0.95),0_1px_2px_rgba(0,0,0,0.95)]">
                  {world.concept}
                </span>
              </button>
            ))}
          </div>
        )}
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button
          type="submit"
          disabled={busy || !name.trim() || !description.trim() || mustPickWorld}
          className="w-full rounded-lg bg-violet-600 px-5 py-3 text-base font-medium text-white hover:bg-violet-500 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {busy
            ? joining
              ? 'Entering the dark…'
              : 'The world takes shape…'
            : joining
              ? `Join party in room ${roomCode.trim()}`
              : mustPickWorld
                ? 'Choose a world to begin'
                : 'Begin a new adventure'}
        </button>
        {busy && !joining && worlds.length === 0 && (
          // Creating with an empty pool generates a world on demand — a real
          // Claude call, up to a minute.
          <p className="text-xs text-zinc-600 text-center">
            A new world is being written for your party — this can take up to a minute.
          </p>
        )}
      </form>
    </div>
  )
}
