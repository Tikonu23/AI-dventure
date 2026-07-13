import { useEffect, useRef, useState } from 'react'
import { fetchSettings, updateSettings, type BackdropMode } from '../api/settings'

// The AI-DVENTURE wordmark doubling as the app menu: click for a dropdown
// (just 'Options' for now), Options opens the settings overlay.
export function TitleMenu() {
  const [menuOpen, setMenuOpen] = useState(false)
  const [optionsOpen, setOptionsOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    function onClickOutside(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [menuOpen])

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setMenuOpen((open) => !open)}
        className="text-base sm:text-lg font-semibold tracking-wide text-zinc-100 uppercase whitespace-nowrap hover:text-violet-300"
        title="Menu"
      >
        AI-dventure
      </button>
      {menuOpen && (
        <div className="absolute left-0 top-full mt-1 z-20 min-w-32 rounded-lg border border-zinc-700 bg-zinc-900 py-1 shadow-lg">
          <button
            type="button"
            onClick={() => {
              setMenuOpen(false)
              setOptionsOpen(true)
            }}
            className="block w-full px-4 py-2 text-left text-sm text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100"
          >
            Options
          </button>
        </div>
      )}
      {optionsOpen && <OptionsOverlay onClose={() => setOptionsOpen(false)} />}
    </div>
  )
}

function OptionsOverlay({ onClose }: { onClose: () => void }) {
  const [mode, setMode] = useState<BackdropMode | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchSettings()
      .then((s) => setMode(s.backdrop_mode))
      .catch(() => setError('Could not load settings.'))
  }, [])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  function choose(next: BackdropMode) {
    setMode(next)
    updateSettings(next).catch(() => setError('Could not save — is the backend up?'))
  }

  return (
    // Backdrop click closes; clicks inside the card don't bubble out.
    <div
      className="fixed inset-0 z-30 flex items-center justify-center bg-black/60 px-6"
      onMouseDown={onClose}
    >
      <div
        onMouseDown={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-xl border border-zinc-700 bg-zinc-900 p-6 space-y-4"
      >
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-100">Options</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-zinc-500 hover:text-zinc-200 text-lg leading-none"
            title="Close"
          >
            ×
          </button>
        </div>

        <fieldset className="space-y-2">
          <legend className="text-xs uppercase tracking-wider text-zinc-500 mb-2">
            Background art
          </legend>
          {(
            [
              ['svg', 'Claude-drawn vector art', 'No extra setup — drawn by the same model that writes the world.'],
              ['grok', 'Grok Imagine (xAI API)', 'Rendered images via the xAI API — needs GROK_KEY in .env. Falls back to vector art on failure.'],
              ['local', 'Local image model (Stable Diffusion)', 'Needs a running SD-WebUI (SD_WEBUI_URL, default localhost:7860). Falls back to vector art if unreachable.'],
            ] as const
          ).map(([value, label, hint]) => (
            <label
              key={value}
              className={`block rounded-lg border px-4 py-3 cursor-pointer ${
                mode === value
                  ? 'border-violet-400 bg-violet-500/10'
                  : 'border-zinc-700 hover:border-zinc-500'
              }`}
            >
              <input
                type="radio"
                name="backdrop-mode"
                className="sr-only"
                checked={mode === value}
                disabled={mode === null}
                onChange={() => choose(value)}
              />
              <span className="block text-sm text-zinc-100">{label}</span>
              <span className="block mt-0.5 text-xs text-zinc-500">{hint}</span>
            </label>
          ))}
        </fieldset>

        <p className="text-xs text-zinc-600">
          Applies to newly generated worlds, for everyone on this server.
        </p>
        {error && <p className="text-xs text-red-400">{error}</p>}
      </div>
    </div>
  )
}
