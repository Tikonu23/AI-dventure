// Per-browser character roster — saved on successful create/join, offered on
// the join screen. Names are unique: making a new character under a saved
// name requires deleting the old one first (enforced by the join screen via
// findCharacter). Kept pure/DOM-free for unit testing, like logic.ts.

export interface SavedCharacter {
  name: string
  description: string
}

const KEY = 'ai-dventure:characters'

export function loadCharacters(): SavedCharacter[] {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as SavedCharacter[]) : []
  } catch {
    return []
  }
}

export function findCharacter(name: string): SavedCharacter | undefined {
  return loadCharacters().find((c) => c.name === name)
}

/** Upserts by name — used only after the join screen's collision check has
 * already allowed the submit, so an existing entry here means "identical". */
export function saveCharacter(character: SavedCharacter): void {
  const others = loadCharacters().filter((c) => c.name !== character.name)
  localStorage.setItem(KEY, JSON.stringify([...others, character]))
}

export function deleteCharacter(name: string): void {
  localStorage.setItem(KEY, JSON.stringify(loadCharacters().filter((c) => c.name !== name)))
}
