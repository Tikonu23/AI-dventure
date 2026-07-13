# AI-dventure

An AI-powered group text adventure. Claude acts as a persistent game master, managing world state through MCP tools and returning structured responses the frontend renders directly.

See `ai-dungeon-master-project-plan.md` for full design, phases, and acceptance criteria.

---

# Stack

**Backend:** Python, FastAPI, Anthropic SDK, MCP Client SDK
**Frontend:** React, TypeScript, Vite, Tailwind, React Query
**Database:** SQLite
**Package manager:** uv
**Test framework:** pytest

---

# Commands

```bash
# Backend
uv run fastapi dev          # start dev server
uv run pytest               # run tests

# Frontend
npm run dev                 # start frontend dev server
```

---

# Key Constraints

- Claude never accesses data directly — everything goes through MCP tools
- Every Claude response must conform to the structured output schema (see plan)
- Schema violations retry once, then degrade gracefully — not silently swallowed
- Evals are deliverables per phase, not afterthoughts
- Combat math and turn order live in code, not in Claude's narration
- Pre-authored world facts (weak spots, puzzle solutions) are stored in SQLite at world-gen time and retrieved — never re-derived from narrative


---

# Commenting Style

Comments narrate the phase of the algorithm as it's entered, not after.
They explain the rationale behind a choice, not what the code already says.
When an external constraint or business rule drives a decision, name it.
Flag assumptions at the callsite, briefly — only where they matter.
Note deliberate implementation choices when the alternative was reasonable.
Stay silent when the code is obvious. Write more when it gets hairy.
Never restate what a well-named variable or method already says.

## Examples

```csharp
// Building the transition map here — valid state moves live in one place
// so routing logic doesn't have to know about states at all

// This assumes the incident is already persisted before we route it
// Caller is responsible for that

// At this point we know the move is legal, just apply it

// SLA clock starts on assignment, not creation — that's the business rule

// Persist all changes in one shot rather than per-incident
```