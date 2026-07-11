import { useState, type FormEvent } from 'react'
import { createGame, joinGame } from '../api/games'
import type { Session } from '../types'

interface Props {
  onSession: (session: Session) => void
  // Prefilled when the player arrived via an invite link (/room/CODE).
  initialRoomCode?: string
}

const inputClasses =
  'w-full rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-3 text-base text-zinc-100 ' +
  'placeholder-zinc-600 focus:outline-none focus:border-violet-400 focus:ring-1 focus:ring-violet-400'

/** Pre-game gate: forge a character, then either join an existing room by
 * code or start a fresh game (which mints a new code to share). */
export function JoinScreen({ onSession, initialRoomCode }: Props) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [roomCode, setRoomCode] = useState(initialRoomCode ?? '')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const joining = roomCode.trim().length > 0

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmedName = name.trim()
    const trimmedDescription = description.trim()
    if (!trimmedName || !trimmedDescription || busy) return

    setBusy(true)
    setError(null)
    try {
      const code = roomCode.trim().toUpperCase()
      const result = joining
        ? { game_id: code, ...(await joinGame(code, trimmedName, trimmedDescription)) }
        : await createGame(trimmedName, trimmedDescription)
      onSession({
        roomCode: result.game_id,
        playerId: result.player_id,
        playerToken: result.player_token,
        playerName: result.name,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setBusy(false)
    }
  }

  return (
    <div className="h-screen flex items-center justify-center bg-zinc-950 px-6">
      <form onSubmit={handleSubmit} className="w-full max-w-md space-y-4">
        <h1 className="text-lg font-semibold tracking-wide text-zinc-100 uppercase text-center">
          AI Dungeoneer
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
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button
          type="submit"
          disabled={busy || !name.trim() || !description.trim()}
          className="w-full rounded-lg bg-violet-600 px-5 py-3 text-base font-medium text-white hover:bg-violet-500 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {busy
            ? joining
              ? 'Entering the dark…'
              : 'The world takes shape…'
            : joining
              ? `Join party in room ${roomCode.trim()}`
              : 'Begin a new adventure'}
        </button>
        {busy && !joining && (
          // Creating may generate a world on demand when the ready pool is
          // empty — that's a real Claude call, up to a minute.
          <p className="text-xs text-zinc-600 text-center">
            A new world is being written for your party — this can take up to a minute.
          </p>
        )}
      </form>
    </div>
  )
}
