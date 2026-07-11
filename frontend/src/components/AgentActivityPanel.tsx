export interface ToolActivity {
  tool: string
  status: 'running' | 'done'
}

interface Props {
  activity: ToolActivity[]
}

export function AgentActivityPanel({ activity }: Props) {
  return (
    // Desktop-only: on a phone this debug-flavored panel would steal most of
    // the narrative column's width.
    <aside className="hidden md:block w-64 shrink-0 border-l border-zinc-800 px-4 py-4 overflow-y-auto">
      <h2 className="text-xs uppercase tracking-wide text-zinc-500 mb-3">
        Agent Activity
      </h2>
      {activity.length === 0 && (
        <p className="text-sm text-zinc-600">No tool calls yet.</p>
      )}
      <ul className="space-y-2">
        {activity.map((a, i) => (
          <li key={i} className="flex items-center gap-2 text-sm font-mono">
            <span
              className={
                a.status === 'running'
                  ? 'h-2 w-2 rounded-full bg-amber-400 animate-pulse'
                  : 'h-2 w-2 rounded-full bg-emerald-500'
              }
            />
            <span className="text-zinc-300">{a.tool}</span>
            <span className="text-zinc-600">{a.status}</span>
          </li>
        ))}
      </ul>
    </aside>
  )
}
