import { useEffect, useState } from 'react'
import type { DiceRoll } from '../types'

const FACE_CYCLE_MS = 80
// The result usually lands well under a second after the click — the box
// tumbles a beat before settling so the roll reads as a roll, not a flicker.
const REVEAL_MS = 800

// Flat d20 icon: hexagon silhouette, central face triangle, edge lines out
// to the corners. Drawn, not an asset — it inherits currentColor, so the
// same die renders every phase (idle, tumbling, settled) by class alone.
function D20({ value, className }: { value: string; className: string }) {
  return (
    <svg viewBox="0 0 64 64" aria-hidden className={className}>
      <g stroke="currentColor" strokeWidth="2.5" fill="none" strokeLinejoin="round">
        <polygon points="32,2 58,17 58,47 32,62 6,47 6,17" />
        <polygon points="32,16 48,42 16,42" />
        <line x1="32" y1="2" x2="32" y2="16" />
        <line x1="32" y1="16" x2="6" y2="17" />
        <line x1="32" y1="16" x2="58" y2="17" />
        <line x1="16" y1="42" x2="6" y2="17" />
        <line x1="16" y1="42" x2="6" y2="47" />
        <line x1="16" y1="42" x2="32" y2="62" />
        <line x1="48" y1="42" x2="58" y2="17" />
        <line x1="48" y1="42" x2="58" y2="47" />
        <line x1="48" y1="42" x2="32" y2="62" />
      </g>
      <text
        x="32"
        y="37"
        textAnchor="middle"
        fontSize={value.length > 2 ? 11 : 14}
        fontWeight="700"
        fill="currentColor"
        stroke="none"
      >
        {value}
      </text>
    </svg>
  )
}

function breakdown(result: DiceRoll): string {
  const mod =
    result.modifier > 0 ? ` + ${result.modifier}` : result.modifier < 0 ? ` − ${-result.modifier}` : ''
  // A single unmodified die needs no arithmetic shown.
  if (result.rolls.length === 1 && !mod) return result.expression
  return `${result.expression}: ${result.rolls.join(' + ')}${mod} = ${result.total}`
}

function sidesOf(expression: string): number {
  return Number(/d(\d+)/i.exec(expression)?.[1] ?? 20)
}

// Cycles random faces while `spinning`, for both the prompt and the box.
function useFaceCycle(spinning: boolean, sides: number): string {
  const [face, setFace] = useState('?')
  useEffect(() => {
    if (!spinning) return
    const id = setInterval(
      () => setFace(String(1 + Math.floor(Math.random() * sides))),
      FACE_CYCLE_MS,
    )
    return () => clearInterval(id)
  }, [spinning, sides])
  return face
}

/** The blocking prompt docked above the input while a roll is pending.
 * Unmounts when the result arrives — DieRollBox takes over in the stream. */
export function DiceRollPrompt({
  expression,
  canRoll,
  actor,
  onRoll,
}: {
  expression: string
  // Only the acting player gets the clickable die; everyone else watches.
  canRoll: boolean
  actor: string | null
  onRoll: () => void
}) {
  const [clicked, setClicked] = useState(false)
  const face = useFaceCycle(clicked, sidesOf(expression))

  const body = (
    <div className="flex items-center justify-center gap-4">
      {clicked ? (
        <D20 value={face} className="h-16 w-16 dice-tumble text-amber-300" />
      ) : (
        <D20
          value={String(sidesOf(expression))}
          className={`h-16 w-16 ${canRoll ? 'text-amber-300' : 'text-zinc-600'}`}
        />
      )}
      <div className="text-sm">
        {clicked ? (
          <span className="text-amber-300/80">The die tumbles…</span>
        ) : canRoll ? (
          <span className="text-amber-300">Fate hangs in the balance — roll {expression}</span>
        ) : (
          <span className="text-zinc-500">
            {actor ?? 'The party'} holds the dice ({expression})…
          </span>
        )}
      </div>
    </div>
  )

  return (
    <div className="px-4 sm:px-6 py-2">
      {canRoll && !clicked ? (
        <button
          type="button"
          onClick={() => {
            setClicked(true)
            onRoll()
          }}
          className="w-full rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2 hover:bg-amber-500/20 animate-pulse"
        >
          {body}
        </button>
      ) : (
        <div
          className={`w-full rounded-lg border px-4 py-2 ${
            clicked ? 'border-amber-500/40 bg-amber-500/10' : 'border-zinc-800 bg-zinc-900 animate-pulse'
          }`}
        >
          {body}
        </div>
      )}
    </div>
  )
}

/** The roll's permanent marker, anchored in the narrative stream where it
 * happened. A just-resolved roll (animate) tumbles briefly on mount, then
 * settles on the server's number — the die must land on that, never one of
 * its own. Rolls loaded from history render already settled. */
export function DieRollBox({ roll, animate = false }: { roll: DiceRoll; animate?: boolean }) {
  const [revealed, setRevealed] = useState(!animate)
  const face = useFaceCycle(!revealed, sidesOf(roll.expression))

  useEffect(() => {
    if (revealed) return
    const id = setTimeout(() => setRevealed(true), REVEAL_MS)
    return () => clearTimeout(id)
  }, [revealed])

  return (
    <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2">
      <div className="flex items-center justify-center gap-3">
        {revealed ? (
          // The settle pop only for live reveals — a reload shouldn't
          // replay it on every historical box.
          <D20
            value={String(roll.total)}
            className={`h-10 w-10 text-amber-300 ${animate ? 'dice-settle' : ''}`}
          />
        ) : (
          <D20 value={face} className="h-10 w-10 dice-tumble text-amber-300" />
        )}
        <span className={`text-sm ${revealed ? 'text-amber-300 font-semibold' : 'text-amber-300/80'}`}>
          {revealed ? breakdown(roll) : 'The die tumbles…'}
        </span>
      </div>
    </div>
  )
}
