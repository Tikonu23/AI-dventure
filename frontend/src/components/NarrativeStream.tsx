export interface LogEntry {
  role: 'player' | 'narrator'
  text: string
}

interface Props {
  log: LogEntry[]
  streamingText: string
}

export function NarrativeStream({ log, streamingText }: Props) {
  return (
    <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
      {log.map((entry, i) => (
        <p
          key={i}
          className={
            entry.role === 'player'
              ? 'text-violet-300 italic'
              : 'text-zinc-200 leading-relaxed whitespace-pre-wrap'
          }
        >
          {entry.role === 'player' ? `> ${entry.text}` : entry.text}
        </p>
      ))}
      {streamingText && (
        <p className="text-zinc-200 leading-relaxed whitespace-pre-wrap">
          {streamingText}
          <span className="animate-pulse">▍</span>
        </p>
      )}
    </div>
  )
}
