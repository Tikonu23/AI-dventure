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
    <form onSubmit={handleSubmit} className="px-4 sm:px-6 py-3 sm:py-4 flex gap-2 sm:gap-3 border-t border-zinc-800">
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={disabled}
        placeholder="What do you do?"
        autoFocus
        className="flex-1 rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-3 text-base text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-violet-400 focus:ring-1 focus:ring-violet-400 disabled:opacity-40"
      />
      <button
        type="submit"
        disabled={disabled}
        className="rounded-lg bg-violet-600 px-5 py-3 text-base font-medium text-white hover:bg-violet-500 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        Act
      </button>
    </form>
  )
}
