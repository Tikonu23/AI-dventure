interface Props {
  npcs: string[]
}

export function NpcRoster({ npcs }: Props) {
  if (npcs.length === 0) return null
  return (
    <div className="px-6 py-2 text-sm text-zinc-400">
      <span className="text-zinc-500">Present: </span>
      {npcs.join(', ')}
    </div>
  )
}
