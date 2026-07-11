---
name: verify
description: Build, launch, and drive AI Dungeoneer end-to-end (backend API + two-browser UI) to verify changes at the real surface.
---

# Verifying AI Dungeoneer

## Launch

```bash
# Backend — do NOT use `fastapi dev`: its emoji banner crashes on the Windows
# console codepage (UnicodeEncodeError, cp1252). Use uvicorn with UTF-8 forced.
cd backend && PYTHONIOENCODING=utf-8 uv run uvicorn app.main:app --port 8123

# Frontend (vite proxies /api -> 127.0.0.1:8123)
cd frontend && npm run dev     # http://localhost:5173
```

Gotchas:
- **Check for a stale server on 8123 first** (`curl -s 127.0.0.1:8123/openapi.json`).
  Orphaned uvicorn reload children survive their parent; find them via
  `Get-CimInstance Win32_Process` filtering command lines for `uvicorn`/`mcp_servers`
  (the port's `OwningProcess` PID may already be dead).
- Killing the backend must also kill its two MCP stdio subprocesses
  (command lines contain `mcp_servers`).
- Schema is created on startup; deleting `backend/world.db*` gives a fresh DB.
- Worlds are AI-generated into a ready pool (`WORLD_POOL_SIZE`, default 1) by a
  startup background task. On a fresh DB the first create usually generates
  on demand (~60s, real Claude call, frontend shows "The world takes shape…");
  once the pool has refilled, creates claim instantly. Tests fake generation
  via `worldgen.generate_world` monkeypatch; `worldgen.FALLBACK_WORLD` is the
  hand-authored template used by tests and the degrade path.

## Drive

- API surface: create room `POST /games {name, description}` → join
  `POST /games/{code}/join` → snapshot `GET /games/{code}/state?token=` →
  subscribe `GET /games/{code}/events` (SSE, all turn events broadcast here) →
  act `POST /games/{code}/turn {token, message, log_player_action}` (409 while
  a turn is in flight). Real turns cost tokens and take 20–60s each.
- UI surface: playwright is NOT a project dep, but chromium is cached in
  `$LOCALAPPDATA/ms-playwright`. `npm i playwright` in a scratchpad dir and
  drive two browser contexts (create in A, join by room code in B, act in one,
  assert the other streams it). Session persists in
  `localStorage['ai-dventure:session']`.
- Cleanup path: backdate a game
  (`UPDATE games SET last_active_at = datetime('now','-31 days')`) and restart
  the backend — the cleanup loop's first tick runs at startup.

## Flows worth driving

Two-browser create/join, spectator streaming, 409 contention while a turn is
in flight, backend restart mid-game (history must round-trip into a working
model turn — SDK content blocks are whitelisted to API input shape in
`db.save_turn`), stale-session 404 → JoinScreen.
