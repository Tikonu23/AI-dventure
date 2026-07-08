# AI Dungeoneer

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
