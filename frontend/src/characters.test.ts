import { beforeEach, describe, expect, it } from 'vitest'
import { deleteCharacter, findCharacter, loadCharacters, saveCharacter } from './characters'

// Node has no localStorage — a Map-backed stand-in is all the store needs.
const store = new Map<string, string>()
globalThis.localStorage = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, v),
  removeItem: (k: string) => void store.delete(k),
} as Storage

beforeEach(() => store.clear())

describe('character roster', () => {
  it('saves and loads characters', () => {
    saveCharacter({ name: 'Thorin', description: 'a dwarf warrior' })
    saveCharacter({ name: 'Mira', description: 'a wizard' })
    expect(loadCharacters().map((c) => c.name)).toEqual(['Thorin', 'Mira'])
  })

  it('finds by exact name', () => {
    saveCharacter({ name: 'Thorin', description: 'a dwarf warrior' })
    expect(findCharacter('Thorin')?.description).toBe('a dwarf warrior')
    expect(findCharacter('thorin')).toBeUndefined()
  })

  it('upserts by name rather than duplicating', () => {
    saveCharacter({ name: 'Thorin', description: 'a dwarf warrior' })
    saveCharacter({ name: 'Thorin', description: 'a dwarf warrior, older now' })
    const all = loadCharacters()
    expect(all).toHaveLength(1)
    expect(all[0].description).toBe('a dwarf warrior, older now')
  })

  it('deletes by name', () => {
    saveCharacter({ name: 'Thorin', description: 'a dwarf warrior' })
    saveCharacter({ name: 'Mira', description: 'a wizard' })
    deleteCharacter('Thorin')
    expect(loadCharacters().map((c) => c.name)).toEqual(['Mira'])
  })

  it('treats corrupt storage as empty', () => {
    store.set('ai-dventure:characters', '{not json')
    expect(loadCharacters()).toEqual([])
  })
})
