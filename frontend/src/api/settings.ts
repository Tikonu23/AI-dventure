export type BackdropMode = 'svg' | 'local' | 'grok'

export interface Settings {
  backdrop_mode: BackdropMode
}

export async function fetchSettings(): Promise<Settings> {
  const response = await fetch('/api/settings')
  if (!response.ok) throw new Error(`settings request failed: ${response.status}`)
  return (await response.json()) as Settings
}

export async function updateSettings(backdropMode: BackdropMode): Promise<void> {
  const response = await fetch('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ backdrop_mode: backdropMode }),
  })
  if (!response.ok) throw new Error(`settings update failed: ${response.status}`)
}
