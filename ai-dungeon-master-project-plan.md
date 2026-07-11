# AI Dungeoneer
## Project Plan (Anthropic + MCP)

---

# Goal

Build a web application where players drop into an AI-generated adventure with minimal setup — no character sheets, no backstory prompts. Claude acts as a persistent game master, managing world state through MCP tools and narrating a living world that responds to player actions.

This is not a chatbot pretending to run a game. It is an AI agent that plans, retrieves world state, validates actions against pre-authored facts, generates assets, and narrates through structured tool use — all visible to the player in real time.

Portfolio demonstrates:

- Anthropic API + structured output
- Model Context Protocol (MCP)
- Agent architecture and tool orchestration
- Persistent world state
- Streaming UX
- Evaluation harness for LLM output quality

---

# Adventure Modes

Each mode is a system prompt + world seed + tone rules. The structured output schema is identical across all modes — only the register and world-generation logic differs.

**Darkest Dungeon** — grimdark, punishing, atmospheric dread. High stakes, morally ambiguous. Gothic horror register.

**Lord of the Rings** — epic high fantasy, heroic register, moral clarity. World feels ancient and consequential.

**Survival** — resource tracking (food, water, health, warmth) lives in SQLite. Claude drives consumption based on actions taken. Every decision has a cost.

**Puzzle** — the most explicit version of what all modes do implicitly: the world has correct answers embedded at generation time. Binary valid/invalid resolution. Easiest mode to eval.

**Random** — picks a mode at random with a random world seed.

**Mystery** — deferred. See stretch goals.

---

# No Character Creation

Players do not make characters. They pick a mode and are dropped into the world. The character is implied by the mode and world context — Claude establishes it in the opening narration. No setup friction. An interviewer can see the full experience in 60 seconds.

---

# Action Validation Model

All modes share the same action validation logic. Two distinct cases:

- **Implausible for the world** — "I fly to the moon." Claude redirects narratively without breaking immersion. ("The ceiling is stone. You are not flying.")
- **Valid but inadvisable** — "I attack the dragon alone." Claude allows it. Consequences follow.

The difference is whether an action violates world physics/rules vs. whether it's merely unwise. Claude never prevents inadvisable actions.

Pre-authored world facts (the dragon's weak spot, the hidden door location) are stored in SQLite at world-generation time. Claude retrieves and checks these before resolving actions. It does not re-derive them from the narrative.

---

# Structured Output Contract

Claude always returns a structured response. The frontend consumes typed fields — it does not scrape prose.

```json
{
  "narrative": "...",
  "location": "The Prancing Pony",
  "exits": { "north": "Market Square", "back": "Town Road" },
  "visible_npcs": ["Gordan (barkeep)", "Hooded stranger"],
  "suggested_actions": ["Talk to the barkeep", "Examine the stranger", "Order a drink"],
  "world_updates": [
    { "type": "location_change", "player": "p1", "to": "tavern_001" }
  ]
}
```

`narrative` streams. Remaining fields arrive with the completed response and drive UI state: exits render as buttons, suggested actions as chips, NPCs populate the roster sidebar.

Handling schema violations (Claude goes off-format) is a first-class concern — retry once, then surface a graceful fallback. This is not an edge case.

## SSE Event Format

The backend pushes three event types to the frontend over a single SSE stream per turn:

```json
{"type": "tool_call", "tool": "sqlite_query", "status": "running"}
{"type": "tool_call", "tool": "sqlite_query", "status": "done"}
{"type": "narrative_chunk", "text": "You push open the door..."}
{"type": "turn_complete", "response": { ...full structured output... }}
```

The Agent Activity Panel consumes `tool_call` events. The narrative stream consumes `narrative_chunk` events. `turn_complete` drives all UI state updates (exits, NPCs, suggested actions, world updates).

---

# Evaluation Harness

Evals are a deliverable, not an afterthought. Fixed input → assert on structured output fields. Prose evals are secondary.

**Tone consistency** — given a fixed input and mode, does the response register match the mode? Darkest Dungeon drifting into cheerful fantasy is a failure. Evaluated per mode using an LLM-as-judge scorer.

**World state consistency** — does Claude honor pre-authored facts? Fix a dragon with a known weak spot; verify correct resolution when a player hits it.

**Action validation** — does Claude correctly redirect implausible actions without breaking immersion? Does it correctly allow inadvisable ones?

---

# Build Phases

Phases are sequenced so there is always a demoable slice. The agent-visible tool orchestration — the most impressive part for interviewers — gets built and polished first.

---

## Phase 1 — MVP Vertical Slice

**What gets built:**
- One mode: Darkest Dungeon
- MCP servers: SQLite, Dice, Filesystem
- World: one dungeon entrance, a handful of rooms, two NPCs
- Structured output contract implemented end to end
- Agent Activity Panel showing every tool call live
- Streaming narrative

**Target scenario:** player enters first room, examines surroundings, takes an action — fully working, including save/reload across server restart.

**Done when:**
- A player action returns a schema-valid structured response every time
- `narrative` streams before `turn_complete` fires
- Tool calls appear in the Agent Activity Panel in real time
- World state survives a server restart (save/reload works)
- Tone consistency eval passes on 5 fixed Darkest Dungeon inputs

---

## Phase 2 — Depth

**What gets built:**
- AI World generation phase instead of pre-generated entrance, rooms, and NPCs. A pool is kept of generated worlds, with the default number of worlds to have prepared set to 1.
- A player HUD with animating health & mana orbs and an inventory grid
- LotR and Survival modes (Survival adds resource tracking)
- Context retrieval strategy implemented properly (see below)
- Persistent NPC memory, relationships, quests in a given game
- Combat state and turn handling
- Action validation for implausible vs. inadvisable cases

**Done when:**
- Survival resources update correctly after relevant actions
- An NPC correctly references a memory from a prior session
- Combat HP math is correct across a 3-turn sequence without Claude doing arithmetic
- A quest status updates on objective completion
- Claude does not hallucinate a fact outside its retrieved context scope
- World state consistency eval passes on 10 fixed scenarios across all three modes
- Action validation eval passes: implausible actions redirected, inadvisable ones allowed

---

## Phase 3 — Polish

**What gets built:**
- Puzzle mode and Random mode
- Image generation (NPC portraits, maps) — mocked until here
- Multiplayer: shared input stream, player list, QR code join
- Deployment (Docker, Render / Fly.io)

**Done when:**
- Two players can join the same campaign via session URL and see current state
- A new NPC generates a portrait once and retrieves it on all subsequent appearances
- Docker container builds and serves the app cleanly
- Puzzle mode correctly accepts only valid solutions and rejects wrong ones

---

## Stretch Goals

- **Mystery mode** — pre-authored hidden truth state, clue planting at world generation, player discovery tracking. Deferred due to complexity of clue consistency evals.
- **Git MCP** — campaign versioning and revert. Overlaps with SQLite snapshot state; revisit only if there's a clear need.

---

# Tech Stack

**Frontend:** React, TypeScript, Vite, Tailwind, React Query

**Backend:** Python, FastAPI, Anthropic SDK (Python), MCP Client SDK

**Package manager:** uv

**Test framework:** pytest

**Database:** SQLite

**Auth:** Simple local login initially

**Deployment:** Docker, Render / Fly.io / Railway

---

# Core Architecture

```
Browser
  ↓
Backend Agent
  ↓
Claude (Anthropic API)
  ↓
MCP Client
  ↓
MCP Servers: SQLite | Dice | Filesystem | Image Generation
```

Claude never directly accesses data. Everything goes through MCP.

Independent tool calls fire in parallel. Dependent calls chain in order. A turn resolving through five parallel MCP calls is fast; five sequential round-trips is not. Reserve strict ordering for genuinely dependent calls (e.g. "find the town" before "find the tavern in that town").

---

# UI Layout

```
[ Mode / Campaign Sidebar ] [ Narrative Stream          ] [ Agent Activity Panel ]
                            [ NPC Roster                ]
                            [ Exit Buttons              ]
                            [ Suggested Action Chips    ]
                            [ Player Input              ]
                            [ Player List               ]
```

The Agent Activity Panel is the demo anchor. Interviewers watch the agent plan and fire tool calls in real time.

---

# Session & Player Model

Single-player for Phase 1–2. Multiplayer in Phase 3.

**Multiplayer:** one shared input stream. All players type into the same channel. Turn resolution is a bounded collection window, not FIFO (revised — FIFO rewards whoever types fastest): actions submitted within the window are collected, non-responders are treated as observing, and Claude synthesizes the group's inputs into one cohesive turn — similar/overlapping actions merge, conflicting ones (some attack, one flees) are narrated as in-party tension, not split into separate outcomes. The party always resolves as a single unit: one location, one narrative thread. Literal party-splitting (multiple locations/threads at once) is out of scope — it would break the single-location schema this whole design leans on. Requires per-player identity and a session/roster, which don't exist yet (Phase 1 has one hardcoded player_id) — that's the real Phase 3 prerequisite, not the resolution logic itself.

**New player joins:** hydrate from current DB state. No history replay. They enter the world as it exists now, the same as joining an adventure already in progress.

**QR code / session URL:** trivial once the session model exists. Deferred to Phase 3.

---

# World Structure

```
Campaign
  └─ Locations
       └─ NPCs
            ├─ Inventory
            ├─ Relationships (numeric: trust, fear, friendship, hatred)
            └─ Memories
  └─ Quests
       └─ Objectives, Status, Reward, NPC Owner
  └─ Monsters
  └─ Items
```

Every entity has a UUID. Everything persists. Claude never regenerates what is already stored.

Pre-authored world facts (weak spots, hidden doors, puzzle solutions) live in a flexible key-value store against their entity, not as hardcoded columns. This keeps the schema stable as modes add new fact types.

---

# MCP Servers

## SQLite

World state: locations, NPCs, relationships, quests, inventory, combat state, session history, faction reputation.

Survival mode extends the schema with resource levels (food, water, health, warmth) per player.

## Filesystem

Campaign markdown: session notes, world lore, generated descriptions.

## Dice

`roll(expression)` — e.g. `2d6+3`, `1d20+5`. Claude never invents rolls.

## Image Generation

NPC portraits, maps, items, monsters. Phase 3. Mock responses acceptable until core loop is solid.

## Git (stretch)

Overlaps with what SQLite snapshot state already provides. Not core demo value.

---

# Context Retrieval Strategy

The hardest design problem in the project. On any given turn, what subset of world state loads into Claude's context?

- Load everything → blows context budget as the world grows.
- Load too little → Claude hallucinates stored facts, defeating the purpose of persistent memory.

Default scope: current location, NPCs present, active quest, player resources (Survival). Expand only when Claude's plan requires something outside that scope (e.g. player explicitly references a past session).

Design this before Phase 2. Everything in that phase depends on it.

---

# Persistent NPC Memory

Each NPC stores: name, age, occupation, description, voice, relationships, known secrets, disposition, inventory, last seen, memories.

Example memory: "The party rescued me from goblins." Claude retrieves this on subsequent interactions. It does not hallucinate it.

**Cast pregeneration:** rather than Claude improvising new NPCs mid-scene (which then need a portrait generated live, on the fly, for whatever it just invented), pregenerate a cast into this schema at world-gen/campaign-creation time — same "pre-authored, retrieved never re-derived" pattern already used for world facts and NPC portraits. Hybrid, not fully fixed: a core cast tied to specific locations/plot beats (as Brother Aldric and The Collector already are) plus a smaller reserve pool of not-yet-placed characters Claude can pull from when it needs to introduce someone new — a fully rigid pregenerated cast risks feeling railroaded if players wander somewhere the roster doesn't cover.

---

# Combat

State in SQLite: turn order, HP, initiative, conditions, buffs/debuffs.

Dice rolls through Dice MCP. Claude narrates and decides what action an enemy takes — it does not do HP arithmetic. Turn order, damage calculation, and condition tracking live in code via the SQLite server. Claude's job is narration and monster decision-making, not math.

---

# Tool Failure Handling

Per server: retry once on transient failure, then degrade gracefully.

A failed SQLite write must not allow Claude to narrate an outcome that was never saved. Consistency between narrated world state and DB state is a hard requirement, not a nice-to-have.

Define fallback behavior per server before Phase 1 is considered done.

---

# Quests

Each quest: ID, title, description, objectives, current progress, reward, NPC owner, status, completed date.

---

# Map Generation

Locations generated once at world creation. Saved permanently. Claude retrieves them — it never regenerates.

---

# Image Generation

When a new NPC appears: check if portrait exists → generate if not → save reference. Phase 3.
