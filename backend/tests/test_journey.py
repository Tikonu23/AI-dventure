"""Journey-paced wins and the fog-of-war map: resolution steps complete one
at a time, complete_game is code-gated behind all of them, visits accumulate
on movement, and /state's map never leaks unvisited rooms."""

import json
import sqlite3

import pytest

from app import db
from app.mcp_servers import sqlite_server


@pytest.fixture
def world(world_db, make_world, monkeypatch):
    monkeypatch.setattr(sqlite_server, "DB_PATH", world_db)
    return make_world()


def test_steps_complete_once_and_gate_the_win(world):
    game = db.create_game("Thorin", "a dwarf warrior", world)
    game_id = game["game_id"]

    resolution = sqlite_server.get_resolution(game_id)
    assert len(resolution["steps"]) == 3
    assert all(not s["done"] for s in resolution["steps"])

    # Winning early is refused in code, not on trust.
    refused = sqlite_server.complete_game(game_id)
    assert "error" in refused and "0 of 3" in refused["error"]
    assert db.get_game(game_id)["status"] == "active"

    assert sqlite_server.complete_resolution_step(game_id, 0) == {
        "steps_done": 1,
        "steps_total": 3,
    }
    assert "error" in sqlite_server.complete_resolution_step(game_id, 0)  # already done
    assert "error" in sqlite_server.complete_resolution_step(game_id, 9)  # unknown

    sqlite_server.complete_resolution_step(game_id, 1)
    assert "error" in sqlite_server.complete_game(game_id)  # 2 of 3

    sqlite_server.complete_resolution_step(game_id, 2)
    assert sqlite_server.complete_game(game_id)["status"] == "won"


def test_legacy_world_without_resolution_still_completable(world_db, world):
    game = db.create_game("Thorin", "a dwarf warrior", world)
    conn = sqlite3.connect(world_db)
    conn.execute("UPDATE worlds SET resolution_json = NULL WHERE id = ?", (world["id"],))
    conn.commit()
    conn.close()
    assert sqlite_server.complete_game(game["game_id"])["status"] == "won"


def test_moves_accumulate_visits_idempotently(world):
    game = db.create_game("Thorin", "a dwarf warrior", world)
    game_id = game["game_id"]

    start_map = db.get_visited_map(game_id)
    assert [r["name"] for r in start_map["rooms"]] == ["The Ruined Gate"]
    # The unvisited crypt shows only as an anonymous stub.
    assert start_map["edges"] == []
    assert start_map["stubs"] == [{"from": f"{world['id']}:dungeon_entrance", "direction": "north"}]

    sqlite_server.move_party(game_id, "north")
    sqlite_server.move_party(game_id, "south")
    sqlite_server.move_party(game_id, "north")  # revisits must not duplicate

    visited = db.get_visited_map(game_id)
    assert {r["name"] for r in visited["rooms"]} == {"The Ruined Gate", "Crypt Hall"}
    # Both directions of the travelled passage are edges now; the ossuary
    # door is a stub, and its name appears nowhere in the payload.
    assert len(visited["edges"]) == 2
    assert {s["direction"] for s in visited["stubs"]} == {"east"}
    assert "Ossuary" not in json.dumps(visited)


def test_state_exposes_map_and_milestones(client):
    created = client.post(
        "/games", json={"name": "Thorin", "description": "a dwarf warrior"}
    ).json()
    state = client.get(
        f"/games/{created['game_id']}/state", params={"token": created["player_token"]}
    ).json()
    assert [r["name"] for r in state["map"]["rooms"]] == ["The Ruined Gate"]
    assert state["milestones"] == {"done": 0, "total": 3}
