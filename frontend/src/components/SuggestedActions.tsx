interface Props {
  actions: string[]
  onSelect: (action: string) => void
  disabled: boolean
}

export function SuggestedActions({ actions, onSelect, disabled }: Props) {
  if (actions.length === 0) return null
  return (
    <div className="px-6 py-2 flex gap-2 flex-wrap">
      {actions.map((action, i) => (
        <button
          key={i}
          type="button"
          disabled={disabled}
          onClick={() => onSelect(action)}
          className="rounded-full bg-zinc-800 px-3 py-1 text-sm text-zinc-300 hover:bg-zinc-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {action}
        </button>
      ))}
    </div>
  )
}
