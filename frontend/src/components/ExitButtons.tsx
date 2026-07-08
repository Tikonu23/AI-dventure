interface Props {
  exits: Record<string, string>
  onExit: (direction: string) => void
  disabled: boolean
}

export function ExitButtons({ exits, onExit, disabled }: Props) {
  const directions = Object.keys(exits)
  if (directions.length === 0) return null
  return (
    <div className="px-6 py-2 flex gap-2 flex-wrap">
      {directions.map((direction) => (
        <button
          key={direction}
          type="button"
          disabled={disabled}
          onClick={() => onExit(direction)}
          className="rounded border border-zinc-700 px-3 py-1 text-sm text-zinc-300 hover:border-violet-400 hover:text-violet-300 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Go {direction}
        </button>
      ))}
    </div>
  )
}
