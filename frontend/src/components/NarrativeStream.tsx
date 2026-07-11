import { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import { useTypewriter } from '../hooks/useTypewriter'
import type { LogEntry } from '../types'

interface Props {
  log: LogEntry[]
  streamingText: string
  isStreaming: boolean
  // Whose action is currently resolving — shown while waiting so spectators
  // know why their input is disabled.
  actor?: string
  // This browser's player id: their own bubbles sit right in violet,
  // teammates' sit left in blue, chat-style.
  selfId: string
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

export function NarrativeStream({ log, streamingText, isStreaming, actor, selfId }: Props) {
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
    <div ref={containerRef} className="flex-1 overflow-y-auto px-4 sm:px-6 py-4">
      <div className="max-w-3xl mx-auto space-y-4">
        {log.map((entry, i) =>
          entry.role === 'player' ? (
            entry.player_id === selfId ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[80%]">
                  {entry.player_name && (
                    <p className="text-xs text-violet-400/70 text-right mb-0.5 pr-1">
                      {entry.player_name}
                    </p>
                  )}
                  <p className="rounded-2xl rounded-tr-sm border border-violet-500/30 bg-violet-500/10 px-4 py-2 text-violet-200">
                    {entry.text}
                  </p>
                </div>
              </div>
            ) : (
              <div key={i} className="flex justify-start">
                <div className="max-w-[80%]">
                  {entry.player_name && (
                    <p className="text-xs text-sky-400/70 mb-0.5 pl-1">{entry.player_name}</p>
                  )}
                  <p className="rounded-2xl rounded-tl-sm border border-sky-400/30 bg-sky-400/10 px-4 py-2 text-sky-200">
                    {entry.text}
                  </p>
                </div>
              </div>
            )
          ) : entry.role === 'system' ? (
            <p key={i} className="text-center text-sm italic text-zinc-500">
              {entry.text}
            </p>
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
          // Tool calls (get_location, move_party, ...) run before any
          // narrative text streams — without this, that gap looks dead.
          <div className="flex items-center gap-2 py-1">
            <span className="h-1.5 w-1.5 rounded-full bg-zinc-600 animate-bounce [animation-delay:-0.3s]" />
            <span className="h-1.5 w-1.5 rounded-full bg-zinc-600 animate-bounce [animation-delay:-0.15s]" />
            <span className="h-1.5 w-1.5 rounded-full bg-zinc-600 animate-bounce" />
            {actor && <span className="text-sm italic text-zinc-500">{actor} acts…</span>}
          </div>
        )}
      </div>
    </div>
  )
}
