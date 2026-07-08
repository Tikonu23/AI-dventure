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
    <form onSubmit={handleSubmit} className="px-6 py-4 flex gap-2 border-t border-zinc-800">
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={disabled}
        placeholder="What do you do?"
        className="flex-1 rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-violet-400 disabled:opacity-40"
      />
      <button
        type="submit"
        disabled={disabled}
        className="rounded bg-violet-600 px-4 py-2 text-white hover:bg-violet-500 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        Act
      </button>
    </form>
  )
}
