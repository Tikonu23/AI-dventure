"""Shared fixtures for the multiplayer test suite.

WORLD_DB_PATH gets a throwaway default at import time — importing
app.mcp_servers.sqlite_server runs its schema init immediately, and without
the override it would write a real world.db into the repo from inside the
test run.
"""

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault(
    "WORLD_DB_PATH", str(Path(tempfile.mkdtemp(prefix="ai-dventure-tests-")) / "world.db")
)

from fastapi.testclient import TestClient  # noqa: E402

from app import db, worldgen  # noqa: E402
from app.schemas import StructuredResponse  # noqa: E402


@pytest.fixture
def world_db(tmp_path, monkeypatch):
    """Point both the app-side db module and the MCP server at an isolated
    per-test database, with all tables created."""
    path = tmp_path / "world.db"
    monkeypatch.setenv("WORLD_DB_PATH", str(path))
    db.init_db()
    return path


@pytest.fixture
def make_world(world_db):
    """Insert one hand-authored template world per call. Each game gets its
    own world (they're single-use in production — cleanup deletes a game's
    world, so sharing one across test games would trip the FK)."""

    def _make() -> dict:
        world_id = db.insert_world(worldgen.FALLBACK_WORLD, status="claimed")
        return db.get_world(world_id)

    return _make


CANNED_RESPONSE = StructuredResponse(
    narrative="The dark presses in around the party.",
    location="The Ruined Gate",
    exits={"north": "crypt_hall"},
    visible_npcs=[],
    suggested_actions=["Look around"],
    world_updates=[],
)


class FakeAgentLoop:
    """Stands in for AgentLoop in endpoint tests — no Anthropic, no MCP.
    Mirrors the real contract: returns (StructuredResponse, new_history)
    where new_history includes the incoming action and an assistant reply
    carrying a pydantic content block (exercises save_turn's serializer)."""

    response = CANNED_RESPONSE
    delay = 0.0

    def __init__(self, router, emit):
        self.emit = emit

    async def run_turn(self, game_id, roster, world, history, player_action):
        import asyncio

        if self.delay:
            await asyncio.sleep(self.delay)
        await self.emit({"type": "narrative_chunk", "text": self.response.narrative})
        new_history = [
            *history,
            {"role": "user", "content": player_action},
            # A real pydantic model in content, like the SDK produces.
            {"role": "assistant", "content": [self.response]},
        ]
        return self.response, new_history


@pytest.fixture
def client(world_db, monkeypatch):
    """TestClient with real lifespan (MCP subprocesses against the isolated
    DB) but the model loop and world generation faked out."""
    import copy

    from app import main

    async def fake_generate_world(client, **kwargs):
        return copy.deepcopy(worldgen.FALLBACK_WORLD)

    monkeypatch.setattr(main, "AgentLoop", FakeAgentLoop)
    # Patched on the worldgen module — main calls it as worldgen.generate_world,
    # and this also keeps the startup pool loop from making real API calls.
    monkeypatch.setattr(worldgen, "generate_world", fake_generate_world)
    # Module-level room state leaks across tests otherwise.
    main.subscribers.clear()
    main.active_turns.clear()
    main.pending_join_notices.clear()
    with TestClient(main.app) as c:
        yield c
