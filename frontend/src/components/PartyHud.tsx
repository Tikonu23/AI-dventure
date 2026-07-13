import type { PartyMember } from '../types'

function Bar({ value, max, barClass }: { value: number; max: number; barClass: string }) {
  return (
    <span className="block h-1 w-24 rounded-full bg-zinc-800 overflow-hidden">
      <span
        className={`block h-full rounded-full ${barClass}`}
        style={{ width: `${max > 0 ? (value / max) * 100 : 0}%` }}
      />
    </span>
  )
}

/** Party vitals, updated live by player_stats events as blows land. */
export function PartyHud({ party }: { party: PartyMember[] }) {
  if (party.length === 0) return null
  return (
    <div className="px-4 sm:px-6 py-2 flex flex-wrap gap-x-5 gap-y-2">
      {party.map((member) => {
        const dead = member.hp === 0
        return (
          <div
            key={member.name}
            className={`flex items-center gap-2 ${dead ? 'opacity-50' : ''}`}
            title={`${member.name} — HP ${member.hp}/${member.max_hp}, MP ${member.mana}/${member.max_mana}`}
          >
            <span className={`text-xs ${dead ? 'line-through text-zinc-600' : 'text-zinc-400'}`}>
              {dead ? `☠ ${member.name}` : member.name}
            </span>
            <span className="space-y-0.5">
              <Bar value={member.hp} max={member.max_hp} barClass="bg-rose-500/80" />
              <Bar value={member.mana} max={member.max_mana} barClass="bg-sky-500/80" />
            </span>
          </div>
        )
      })}
    </div>
  )
}
