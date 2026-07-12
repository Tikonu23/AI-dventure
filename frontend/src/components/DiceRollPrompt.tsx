import { useEffect, useState } from 'react'
import type { DiceResultEvent } from '../types'

interface Props {
  expression: string
  // Only the acting player gets the clickable die; everyone else watches.
  canRoll: boolean
  actor: string | null
  // Server-authoritative result; null while the roll is still pending.
  // The die must land on this number, never one of its own.
  result: DiceResultEvent | null
  onRoll: () => void
}

// The result usually arrives well under a second after the click — tumble a
// beat longer so the roll reads as a roll, not a flicker.
const TUMBLE_MS = 900
const FACE_CYCLE_MS = 80

// Flat d20 icon: hexagon silhouette, central face triangle, edge lines out
// to the corners. Drawn, not an asset — it inherits currentColor, so the
// same die renders every phase (idle, tumbling, settled) by class alone.
function D20({ value, className }: { value: string; className: string }) {
  return (
    <svg viewBox="0 0 64 64" aria-hidden className={`h-16 w-16 ${className}`}>
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

function breakdown(result: DiceResultEvent): string {
  const mod =
    result.modifier > 0 ? ` + ${result.modifier}` : result.modifier < 0 ? ` − ${-result.modifier}` : ''
  // A single unmodified die needs no arithmetic shown.
  if (result.rolls.length === 1 && !mod) return result.expression
  return `${result.expression}: ${result.rolls.join(' + ')}${mod} = ${result.total}`
}

export function DiceRollPrompt({ expression, canRoll, actor, result, onRoll }: Props) {
  const [clicked, setClicked] = useState(false)
  const [revealed, setRevealed] = useState(false)
  // Face shown mid-tumble — random churn, bounded by the die actually rolled.
  const [face, setFace] = useState('?')

  const tumbling = (clicked || result !== null) && !revealed
  const sides = Number(/d(\d+)/i.exec(expression)?.[1] ?? 20)

  useEffect(() => {
    if (!tumbling) return
    const id = setInterval(
      () => setFace(String(1 + Math.floor(Math.random() * sides))),
      FACE_CYCLE_MS,
    )
    return () => clearInterval(id)
  }, [tumbling, sides])

  // Reveal only once the server's number exists AND the tumble has had its
  // beat — whichever comes later.
  useEffect(() => {
    if (result === null) return
    const id = setTimeout(() => setRevealed(true), TUMBLE_MS)
    return () => clearTimeout(id)
  }, [result])

  const die = revealed && result ? (
    <D20 value={String(result.total)} className="dice-settle text-amber-300" />
  ) : tumbling ? (
    <D20 value={face} className="dice-tumble text-amber-300" />
  ) : (
    <D20 value={String(sides)} className={canRoll ? 'text-amber-300' : 'text-zinc-600'} />
  )

  const caption =
    revealed && result ? (
      <span className="text-amber-300 font-semibold">{breakdown(result)}</span>
    ) : tumbling ? (
      <span className="text-amber-300/80">The die tumbles…</span>
    ) : canRoll ? (
      <span className="text-amber-300">Fate hangs in the balance — roll {expression}</span>
    ) : (
      <span className="text-zinc-500">
        {actor ?? 'The party'} holds the dice ({expression})…
      </span>
    )

  const body = (
    <div className="flex items-center justify-center gap-4">
      {die}
      <div className="text-sm">{caption}</div>
    </div>
  )

  return (
    <div className="px-4 sm:px-6 py-2">
      {canRoll && !clicked && result === null ? (
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
            tumbling || revealed
              ? 'border-amber-500/40 bg-amber-500/10'
              : 'border-zinc-800 bg-zinc-900 animate-pulse'
          }`}
        >
          {body}
        </div>
      )}
    </div>
  )
}
