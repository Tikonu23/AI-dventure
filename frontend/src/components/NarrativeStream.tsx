import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import { useTypewriter } from '../hooks/useTypewriter'

export interface LogEntry {
  role: 'player' | 'narrator'
  text: string
}

interface Props {
  log: LogEntry[]
  streamingText: string
  isStreaming: boolean
}

// Claude writes narration with markdown emphasis (**bold**, lists, etc.) —
// these target react-markdown's plain semantic output directly, since no
// @tailwindcss/typography plugin is installed for a one-off prose block.
const proseClasses =
  'font-narrative text-[17px] text-zinc-200 leading-relaxed ' +
  '[&_p]:mb-4 [&_p:last-child]:mb-0 ' +
  '[&_strong]:font-semibold [&_strong]:text-zinc-50 ' +
  '[&_em]:italic [&_em]:text-zinc-300 ' +
  '[&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-4 ' +
  '[&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:mb-4 ' +
  '[&_li]:mb-1'

export function NarrativeStream({ log, streamingText, isStreaming }: Props) {
  // Only the in-flight turn types out — finalized log entries render whole,
  // there's nothing left to reveal.
  const revealed = useTypewriter(streamingText)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    // Stick to the bottom as text streams in, but only if the reader hasn't
    // deliberately scrolled up to re-read something earlier.
    const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100
    if (isNearBottom) el.scrollTop = el.scrollHeight
  }, [log, revealed, isStreaming])

  return (
    <div ref={containerRef} className="flex-1 overflow-y-auto px-6 py-4">
      <div className="max-w-3xl mx-auto space-y-4">
        {log.map((entry, i) =>
          entry.role === 'player' ? (
            <div key={i} className="flex justify-end">
              <p className="max-w-[80%] rounded-2xl rounded-tr-sm border border-violet-500/30 bg-violet-500/10 px-4 py-2 text-violet-200">
                {entry.text}
              </p>
            </div>
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
        {isStreaming && !revealed && (
          // Tool calls (get_location, move_player, ...) run before any
          // narrative text streams — without this, that gap looks dead.
          <div className="flex gap-1 py-1">
            <span className="h-1.5 w-1.5 rounded-full bg-zinc-600 animate-bounce [animation-delay:-0.3s]" />
            <span className="h-1.5 w-1.5 rounded-full bg-zinc-600 animate-bounce [animation-delay:-0.15s]" />
            <span className="h-1.5 w-1.5 rounded-full bg-zinc-600 animate-bounce" />
          </div>
        )}
      </div>
    </div>
  )
}
