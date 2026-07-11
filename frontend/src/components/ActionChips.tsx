interface Props {
  exits: Record<string, string>
  suggestions: string[]
  onSelect: (action: string) => void
  disabled: boolean
}

// Exits (always valid, DB-derived) and the model's suggestions used to render
// as two visually distinct button styles stacked on top of each other with
// no explanation for the split — read as an arbitrary two-tier menu. One
// row, one muted style now; exits get an arrow prefix so they still read as
// "movement" at a glance. Kept visually secondary to the free-text input
// below — these are shortcuts, not the only sanctioned actions.
export function ActionChips({ exits, suggestions, onSelect, disabled }: Props) {
  const chips = [
    ...Object.keys(exits).map((direction) => ({
      key: `exit-${direction}`,
      label: `→ ${direction}`,
      action: `I go ${direction}.`,
    })),
    ...suggestions.map((action, i) => ({
      key: `suggestion-${i}`,
      label: action,
      action,
    })),
  ]
  if (chips.length === 0) return null

  return (
    <div className="px-4 sm:px-6 py-2 flex gap-2 flex-wrap">
      {chips.map((chip) => (
        <button
          key={chip.key}
          type="button"
          disabled={disabled}
          onClick={() => onSelect(chip.action)}
          className="rounded-full border border-zinc-800 bg-zinc-900 px-3 py-1 text-xs text-zinc-400 hover:border-violet-400 hover:text-violet-300 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {chip.label}
        </button>
      ))}
    </div>
  )
}
