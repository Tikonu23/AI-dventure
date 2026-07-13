import { useEffect, useState, type FormEvent } from 'react'
import { createGame, joinGame, listWorlds, WorldTakenError } from '../api/games'
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

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmedName = name.trim()
    const trimmedDescription = description.trim()
    if (!trimmedName || !trimmedDescription || busy || mustPickWorld) return

    setBusy(true)
    setError(null)
    try {
      const code = roomCode.trim().toUpperCase()
      const result = joining
        ? { game_id: code, ...(await joinGame(code, trimmedName, trimmedDescription)) }
        : await createGame(trimmedName, trimmedDescription, worldId ?? undefined)
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
        <h1 className="text-lg font-semibold tracking-wide text-zinc-100 uppercase text-center">
          AI-dventure
        </h1>
        <p className="text-sm text-zinc-500 text-center">
          Forge a character. Your description is your character sheet — the
          world will hold you to it.
        </p>
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
                className={`w-full text-left rounded-lg border px-4 py-3 ${
                  worldId === world.id
                    ? 'border-violet-400 bg-violet-500/10'
                    : 'border-zinc-700 bg-zinc-900 hover:border-zinc-500'
                }`}
              >
                <span className="block text-sm font-medium text-zinc-100">{world.title}</span>
                {/* No `block` here — line-clamp needs its own -webkit-box display. */}
                <span className="mt-1 text-xs text-zinc-500 line-clamp-3">
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
