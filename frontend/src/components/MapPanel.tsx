import { useEffect, useMemo, useRef, useState } from 'react'
import { layoutMap } from '../logic'
import type { GameMap } from '../types'

const CELL = 84
const ROOM_W = 64
const ROOM_H = 34
const MIN_ZOOM = 0.5
const MAX_ZOOM = 3

/** Fog-of-war map: visited rooms, connections (⇅ marks stairs), and dim "?"
 * doors into the dark. Drag to pan, wheel or buttons to zoom; hover/tap a
 * room for its detail. Data is server-filtered — unvisited room names never
 * reach the client at all. */
export function MapPanel({ map, currentName }: { map: GameMap; currentName: string }) {
  const layout = useMemo(() => layoutMap(map), [map])
  const svgRef = useRef<SVGSVGElement>(null)
  // Pan/zoom as a transform on top of the auto-fitted viewBox: user units,
  // so a refit (new room discovered) never discards the user's view.
  const [view, setView] = useState({ x: 0, y: 0, z: 1 })
  const [detailId, setDetailId] = useState<string | null>(null)
  const [hoverId, setHoverId] = useState<string | null>(null)
  const drag = useRef<{ lastX: number; lastY: number; moved: number } | null>(null)

  if (map.rooms.length === 0) return null

  const xs = [...layout.nodes.map((n) => n.x), ...layout.stubs.map((s) => s.x)]
  const ys = [...layout.nodes.map((n) => n.y), ...layout.stubs.map((s) => s.y)]
  const pad = 0.75
  const minX = Math.min(...xs) - pad
  const minY = Math.min(...ys) - pad
  const width = (Math.max(...xs) - minX + pad) * CELL
  const height = (Math.max(...ys) - minY + pad) * CELL
  const px = (x: number) => (x - minX) * CELL
  const py = (y: number) => (y - minY) * CELL

  // Client-pixel deltas → SVG user units (the svg is CSS-scaled to fit).
  function toUserUnits(dx: number, dy: number): [number, number] {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect) return [dx, dy]
    return [(dx * width) / rect.width, (dy * height) / rect.height]
  }

  function zoomBy(factor: number) {
    setView((v) => {
      const z = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.z * factor))
      // Keep the viewBox center fixed while scaling.
      const k = z / v.z
      const cx = width / 2
      const cy = height / 2
      return { z, x: cx - k * (cx - v.x), y: cy - k * (cy - v.y) }
    })
  }

  const detail =
    layout.nodes.find((n) => n.id === (hoverId ?? detailId)) ?? null

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        className="w-full touch-none cursor-grab active:cursor-grabbing select-none"
        style={{ maxHeight: 300 }}
        role="img"
        aria-label="Map of explored rooms"
        // No pointer capture: it would retarget the rooms' own pointer
        // events to the svg and kill room taps. Losing a drag that leaves
        // the map area is a fine trade for a mini-map.
        onPointerDown={(e) => {
          drag.current = { lastX: e.clientX, lastY: e.clientY, moved: 0 }
        }}
        onPointerMove={(e) => {
          if (!drag.current) return
          const [ux, uy] = toUserUnits(e.clientX - drag.current.lastX, e.clientY - drag.current.lastY)
          drag.current.moved += Math.abs(ux) + Math.abs(uy)
          setView((v) => ({ ...v, x: v.x + ux, y: v.y + uy }))
          drag.current.lastX = e.clientX
          drag.current.lastY = e.clientY
        }}
        onPointerUp={(e) => {
          // A still tap on empty map clears the detail (hover too — touch
          // never fires pointerleave, so it would otherwise stick).
          if (drag.current && drag.current.moved < 4 && e.target === e.currentTarget) {
            setDetailId(null)
            setHoverId(null)
          }
          drag.current = null
        }}
      >
        <g transform={`translate(${view.x} ${view.y}) scale(${view.z})`}>
          {layout.links.map((l, i) => {
            const mx = (px(l.x1) + px(l.x2)) / 2
            const my = (py(l.y1) + py(l.y2)) / 2
            return (
              <g key={`l${i}`}>
                <line
                  x1={px(l.x1)}
                  y1={py(l.y1)}
                  x2={px(l.x2)}
                  y2={py(l.y2)}
                  stroke="#3f3f46"
                  strokeWidth="2"
                  strokeDasharray={l.vertical ? '5 4' : undefined}
                />
                {l.vertical && (
                  // Stairs/descent — the only diagonals worldgen can produce.
                  <text
                    x={mx}
                    y={my + 4}
                    textAnchor="middle"
                    fontSize="12"
                    fill="#a1a1aa"
                    stroke="#0b0b0f"
                    strokeWidth="3"
                    paintOrder="stroke"
                  >
                    ⇅
                  </text>
                )}
              </g>
            )
          })}
          {layout.stubs.map((s, i) => (
            <g key={`s${i}`} opacity="0.5">
              <circle cx={px(s.x)} cy={py(s.y)} r="9" fill="#18181b" stroke="#3f3f46" strokeDasharray="3 3" />
              <text x={px(s.x)} y={py(s.y) + 3.5} textAnchor="middle" fontSize="11" fill="#71717a">
                ?
              </text>
            </g>
          ))}
          {layout.nodes.map((n) => {
            const current = n.name === currentName
            const active = n.id === (hoverId ?? detailId)
            return (
              <g
                key={n.id}
                className="cursor-pointer"
                onPointerEnter={() => setHoverId(n.id)}
                onPointerLeave={() => setHoverId(null)}
                onPointerUp={() => {
                  if (!drag.current || drag.current.moved < 4) {
                    setDetailId((prev) => (prev === n.id ? null : n.id))
                  }
                }}
              >
                <rect
                  x={px(n.x) - ROOM_W / 2}
                  y={py(n.y) - ROOM_H / 2}
                  width={ROOM_W}
                  height={ROOM_H}
                  rx="6"
                  fill={current ? 'rgba(139, 92, 246, 0.15)' : active ? '#27272a' : '#18181b'}
                  stroke={current ? '#a78bfa' : active ? '#71717a' : '#52525b'}
                  strokeWidth={current ? 2 : 1}
                />
                <text
                  x={px(n.x)}
                  y={py(n.y) + 3}
                  textAnchor="middle"
                  fontSize="9"
                  fill={current ? '#ddd6fe' : '#a1a1aa'}
                >
                  {n.name.length > 13 ? `${n.name.slice(0, 12)}…` : n.name}
                </text>
              </g>
            )
          })}
        </g>
      </svg>

      {/* Zoom controls — buttons so phones get zoom without pinch support. */}
      <div className="absolute top-1 right-1 flex flex-col gap-1">
        {(
          [
            ['+', () => zoomBy(1.25)],
            ['−', () => zoomBy(1 / 1.25)],
            ['⌂', () => setView({ x: 0, y: 0, z: 1 })],
          ] as const
        ).map(([label, onClick]) => (
          <button
            key={label}
            type="button"
            onClick={onClick}
            className="h-6 w-6 rounded border border-zinc-700 bg-zinc-900/90 text-xs text-zinc-400 hover:text-zinc-100 hover:border-zinc-500 leading-none"
            title={label === '⌂' ? 'Reset view' : label === '+' ? 'Zoom in' : 'Zoom out'}
          >
            {label}
          </button>
        ))}
      </div>

      {detail && (
        <div className="mt-2 rounded-lg border border-zinc-800 bg-zinc-900/80 px-3 py-2">
          <p className="text-xs font-medium text-zinc-100">
            {detail.name}
            {detail.name === currentName && (
              <span className="ml-2 text-[10px] uppercase tracking-wider text-violet-300">
                you are here
              </span>
            )}
          </p>
          <p className="mt-1 text-xs text-zinc-500 leading-relaxed">{detail.description}</p>
        </div>
      )}

      <WheelZoom svgRef={svgRef} zoomBy={zoomBy} />
    </div>
  )
}

/** Wheel zoom needs a non-passive listener (React's onWheel can't
 * preventDefault), attached imperatively. Rendered as a null component so it
 * can live inside MapPanel's early-return-free JSX. */
function WheelZoom({
  svgRef,
  zoomBy,
}: {
  svgRef: React.RefObject<SVGSVGElement | null>
  zoomBy: (factor: number) => void
}) {
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    function onWheel(e: WheelEvent) {
      e.preventDefault()
      zoomBy(e.deltaY < 0 ? 1.15 : 1 / 1.15)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  })
  return null
}
