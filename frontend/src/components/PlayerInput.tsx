import { useState, type FormEvent } from 'react'

interface Props {
  onSubmit: (message: string) => void
  disabled: boolean
}

export function PlayerInput({ onSubmit, disabled }: Props) {
  const [value, setValue] = useState('')

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSubmit(trimmed)
    setValue('')
  }

  return (
    // Border/outer padding live on the parent row — the stat orbs flank this
    // form and share that chrome.
    <form onSubmit={handleSubmit} className="flex-1 min-w-0 px-2 sm:px-3 py-3 sm:py-4 flex gap-2 sm:gap-3">
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={disabled}
        placeholder="What do you do?"
        autoFocus
        // min-w-0: inputs refuse to shrink below their intrinsic width
        // otherwise, overflowing the row into the mana orb on phones.
        className="flex-1 min-w-0 rounded-lg border border-zinc-700 bg-zinc-900 px-3 sm:px-4 py-3 text-base text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-violet-400 focus:ring-1 focus:ring-violet-400 disabled:opacity-40"
      />
      <button
        type="submit"
        disabled={disabled}
        className="shrink-0 rounded-lg bg-violet-600 px-3 sm:px-5 py-3 text-base font-medium text-white hover:bg-violet-500 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        Act
      </button>
    </form>
  )
}
