import { useRef, useState } from 'react'

interface Palette {
  // Liquid body (top → bottom), the two wave surfaces, rim, and glass glow.
  body: string
  waveA: string
  waveB: string
  rim: string
  glow: string
}

// The body span is ~200% of the orb tall, so gradient stops live in its top
// half (the visible region). Edge-darkening ellipse first, then the depth
// ramp — reads as a lit volume, not a flat fill.
const PALETTES = {
  hp: {
    body:
      'radial-gradient(ellipse 120% 45% at 50% 20%, rgba(0,0,0,0) 45%, rgba(0,0,0,0.55) 85%), ' +
      'linear-gradient(180deg, #f87171 0%, #dc2626 10%, #991b1b 24%, #450a0a 46%)',
    waveA: 'rgba(248, 113, 113, 0.55)',
    waveB: 'rgba(239, 68, 68, 0.35)',
    rim: 'rgba(127, 29, 29, 0.9)',
    glow: 'rgba(248, 113, 113, 0.35)',
  },
  mana: {
    body:
      'radial-gradient(ellipse 120% 45% at 50% 20%, rgba(0,0,0,0) 45%, rgba(0,0,0,0.55) 85%), ' +
      'linear-gradient(180deg, #7dd3fc 0%, #38bdf8 10%, #1d4ed8 24%, #0f1e4d 46%)',
    waveA: 'rgba(125, 211, 252, 0.6)',
    waveB: 'rgba(56, 189, 248, 0.35)',
    rim: 'rgba(30, 58, 138, 0.9)',
    glow: 'rgba(96, 165, 250, 0.4)',
  },
} satisfies Record<string, Palette>

/** Diablo-style vitals orb: hazy liquid at the current ratio, numbers on
 * hover or tap. Pure CSS — the liquid is two slow counter-phased waves. */
export function StatOrb({
  kind,
  label,
  value,
  max,
}: {
  kind: keyof typeof PALETTES
  label: string
  value: number
  max: number
}) {
  const palette = PALETTES[kind]
  const ratio = max > 0 ? value / max : 0
  const [shown, setShown] = useState(false)
  const hideTimer = useRef<number | undefined>(undefined)

  // Hover shows while hovering; a tap (mobile) shows for a beat.
  function reveal(transient: boolean) {
    setShown(true)
    window.clearTimeout(hideTimer.current)
    if (transient) hideTimer.current = window.setTimeout(() => setShown(false), 1800)
  }

  return (
    <button
      type="button"
      aria-label={`${label}: ${value} of ${max}`}
      title={`${label} ${value}/${max}`}
      onPointerEnter={() => reveal(false)}
      onPointerLeave={() => setShown(false)}
      onClick={() => reveal(true)}
      className="relative h-16 w-16 sm:h-20 sm:w-20 shrink-0 rounded-full overflow-hidden cursor-pointer select-none"
      style={{
        border: `2px solid ${palette.rim}`,
        boxShadow: `inset 0 6px 14px rgba(0,0,0,0.75), 0 0 18px ${palette.glow}`,
        background: 'radial-gradient(circle at 50% 35%, #17171d 0%, #060608 75%)',
      }}
    >
      {/* Liquid: the wrapper's offset IS the fill level. */}
      <span
        aria-hidden
        className="absolute inset-0 block transition-transform duration-700 ease-out"
        style={{ transform: `translateY(${(1 - ratio) * 100}%)` }}
      >
        {/* The waves' TOP EDGE is the liquid surface: everything below their
            rotating rims reads as liquid, the tilt of the rims is the slosh. */}
        <span
          className="orb-wave block"
          style={{
            top: '0%',
            borderRadius: '42%',
            background: palette.waveA,
            animationDuration: '9s',
          }}
        />
        <span
          className="orb-wave block"
          style={{
            top: '-4%',
            borderRadius: '46%',
            background: palette.waveB,
            animationDuration: '13s',
            animationDirection: 'reverse',
          }}
        />
        {/* Depth gradient just under the surface, past the orb's bottom. */}
        <span
          className="absolute block"
          style={{ top: '12%', left: 0, right: 0, height: '200%', background: palette.body }}
        />
        {/* Inner haze — slow luminous breathing inside the liquid. */}
        <span
          className="orb-haze absolute block blur-md"
          style={{
            top: '25%',
            left: '15%',
            right: '15%',
            height: '70%',
            borderRadius: '50%',
            background: palette.glow,
          }}
        />
      </span>
      {/* Glass highlight over everything. */}
      <span
        aria-hidden
        className="absolute block pointer-events-none"
        style={{
          top: '7%',
          left: '22%',
          width: '42%',
          height: '24%',
          borderRadius: '50%',
          background:
            'linear-gradient(180deg, rgba(255,255,255,0.16), rgba(255,255,255,0.02))',
          filter: 'blur(1.5px)',
        }}
      />
      {shown && (
        <span className="absolute inset-0 flex items-center justify-center text-[11px] sm:text-xs font-semibold text-white/95 [text-shadow:0_1px_3px_rgba(0,0,0,0.95)]">
          {value}/{max}
        </span>
      )}
    </button>
  )
}
