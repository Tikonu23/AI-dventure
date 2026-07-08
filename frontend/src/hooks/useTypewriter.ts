import { useEffect, useRef, useState } from 'react'

/**
 * Reveals `fullText` a few characters at a time on a fixed timer, instead
 * of jumping straight to whatever arrived in the latest SSE chunk — network
 * delivery is bursty (a chunk can be a word or, near the end of a turn,
 * several hundred characters at once), so tying the reveal rate to chunk
 * arrival looks jumpy rather than like typing.
 *
 * Speeds up when the backlog (unrevealed text) is large, so a big burst
 * catches up in well under a second instead of trickling out at the base
 * rate. Resets instantly if `fullText` gets shorter (a new turn started).
 */
export function useTypewriter(fullText: string, tickMs = 20, minCharsPerTick = 2): string {
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
      const step = Math.max(minCharsPerTick, Math.ceil(backlog / 40))
      shownRef.current = target.slice(0, shownRef.current.length + step)
      setShown(shownRef.current)
    }, tickMs)
    return () => clearInterval(id)
  }, [tickMs, minCharsPerTick])

  return shown
}
