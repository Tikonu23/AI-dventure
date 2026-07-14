import { useEffect, useRef, useState } from 'react'

/**
 * Reveals `fullText` a few characters at a time on a fixed timer, instead
 * of jumping straight to whatever arrived in the latest SSE chunk — network
 * delivery is bursty (a chunk can be a word or, near the end of a turn,
 * several hundred characters at once), so tying the reveal rate to chunk
 * arrival looks jumpy rather than like typing.
 *
 * Speeds up when the backlog (unrevealed text) is large, but only up to a
 * hard cap — the reveal is meant to be READ, so it must never outrun a
 * reader just because the model streams fast. Resets instantly if
 * `fullText` gets shorter (a new turn started).
 */
// ~50 chars/s base, ~200 chars/s flat out — brisk but followable.
const MAX_CHARS_PER_TICK = 8

export function useTypewriter(fullText: string, tickMs = 40, minCharsPerTick = 2): string {
  const [shown, setShown] = useState('')
  const shownRef = useRef('')
  const targetRef = useRef(fullText)
  targetRef.current = fullText

  useEffect(() => {
    if (fullText.length < shownRef.current.length) {
      shownRef.current = ''
      setShown('')
    }
  }, [fullText])

  useEffect(() => {
    const id = setInterval(() => {
      const target = targetRef.current
      const backlog = target.length - shownRef.current.length
      if (backlog <= 0) return
      const step = Math.min(
        MAX_CHARS_PER_TICK,
        Math.max(minCharsPerTick, Math.ceil(backlog / 150)),
      )
      shownRef.current = target.slice(0, shownRef.current.length + step)
      setShown(shownRef.current)
    }, tickMs)
    return () => clearInterval(id)
  }, [tickMs, minCharsPerTick])

  return shown
}
