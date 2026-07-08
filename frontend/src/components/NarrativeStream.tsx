import ReactMarkdown from 'react-markdown'
import { useTypewriter } from '../hooks/useTypewriter'

export interface LogEntry {
  role: 'player' | 'narrator'
  text: string
}

interface Props {
  log: LogEntry[]
  streamingText: string
}

// Claude writes narration with markdown emphasis (**bold**, lists, etc.) —
// these target react-markdown's plain semantic output directly, since no
// @tailwindcss/typography plugin is installed for a one-off prose block.
const proseClasses =
  'text-zinc-200 leading-relaxed ' +
  '[&_p]:mb-4 [&_p:last-child]:mb-0 ' +
  '[&_strong]:font-semibold [&_strong]:text-zinc-50 ' +
  '[&_em]:italic [&_em]:text-zinc-300 ' +
  '[&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-4 ' +
  '[&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:mb-4 ' +
  '[&_li]:mb-1'

export function NarrativeStream({ log, streamingText }: Props) {
  // Only the in-flight turn types out — finalized log entries render whole,
  // there's nothing left to reveal.
  const revealed = useTypewriter(streamingText)

  return (
    <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
      {log.map((entry, i) =>
        entry.role === 'player' ? (
          <p key={i} className="text-violet-300 italic">{`> ${entry.text}`}</p>
        ) : (
          <div key={i} className={proseClasses}>
            <ReactMarkdown>{entry.text}</ReactMarkdown>
          </div>
        ),
      )}
      {revealed && (
        <div className={proseClasses}>
          <ReactMarkdown>{revealed}</ReactMarkdown>
          <span className="animate-pulse">▍</span>
        </div>
      )}
    </div>
  )
}
