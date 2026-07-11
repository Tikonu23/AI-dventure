"""get_party/move_party: the party moves as one unit, per game, isolated
between games — and location/npc reads carry their secret facts. Calls the
MCP server's tool functions directly (FastMCP's decorator returns the plain
function) rather than over stdio. Entity ids are world-prefixed
("<world_id>:slug"), globally unique."""

import pytest

from app import db
from app.mcp_servers import sqlite_server


@pytest.fixture
def world(world_db, make_world, monkeypatch):
    # sqlite_server captures DB_PATH at import time — repoint it at this
    # test's isolated file (schema already created by the world_db fixture).
    monkeypatch.setattr(sqlite_server, "DB_PATH", world_db)
    return make_world()


def _loc(world: dict, slug: str) -> str:
    return f"{world['id']}:{slug}"


def test_get_party_returns_starting_position(world):
    game = db.create_game("Thorin", "a dwarf warrior", world)
    party = sqlite_server.get_party(game["game_id"])
    assert party == {
        "game_id": game["game_id"],
        "location_id": _loc(world, "dungeon_entrance"),
    }


def test_get_party_unknown_game(world):
    assert "error" in sqlite_server.get_party("XXXXX")


def test_move_party_through_valid_exit(world):
    game = db.create_game("Thorin", "a dwarf warrior", world)
    moved = sqlite_server.move_party(game["game_id"], "north")
    assert moved == {
        "game_id": game["game_id"],
        "from": _loc(world, "dungeon_entrance"),
        "to": _loc(world, "crypt_hall"),
    }
    assert sqlite_server.get_party(game["game_id"])["location_id"] == _loc(world, "crypt_hall")


def test_move_party_invalid_direction_leaves_state(world):
    game = db.create_game("Thorin", "a dwarf warrior", world)
    result = sqlite_server.move_party(game["game_id"], "down")
    assert "error" in result
    assert sqlite_server.get_party(game["game_id"])["location_id"] == _loc(
        world, "dungeon_entrance"
    )


def test_games_move_independently(world, make_world):
    game_a = db.create_game("Thorin", "a dwarf warrior", world)
    world_b = make_world()
    game_b = db.create_game("Zara", "an elven wizard", world_b)
    sqlite_server.move_party(game_a["game_id"], "north")
    assert sqlite_server.get_party(game_a["game_id"])["location_id"] == _loc(world, "crypt_hall")
    assert sqlite_server.get_party(game_b["game_id"])["location_id"] == _loc(
        world_b, "dungeon_entrance"
    )


def test_get_location_includes_secret_facts(world):
    location = sqlite_server.get_location(_loc(world, "ossuary"))
    assert "hidden_door" in location["facts"]
    # A location with no authored facts returns an empty dict, not an error.
    other = sqlite_server.get_location(_loc(world, "dungeon_entrance"))
    assert other["facts"] == {}


def test_get_npc_includes_secret_facts(world):
    npc = sqlite_server.get_npc(f"{world['id']}:collector")
    assert npc["name"] == "The Collector"
    assert "weakness" in npc["facts"]
