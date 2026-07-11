"""get_party/move_party: the party moves as one unit, per game, isolated
between games. Calls the MCP server's tool functions directly (FastMCP's
decorator returns the plain function) rather than over stdio."""

import pytest

from app import db
from app.mcp_servers import sqlite_server


@pytest.fixture
def world(world_db, monkeypatch):
    # sqlite_server captures DB_PATH at import time — repoint it at this
    # test's isolated file and create the world tables it normally makes at
    # subprocess startup.
    monkeypatch.setattr(sqlite_server, "DB_PATH", world_db)
    conn = sqlite_server._connect()
    sqlite_server._init_db(conn)
    conn.close()
    return world_db


def test_get_party_returns_position(world):
    game = db.create_game("Thorin", "a dwarf warrior")
    party = sqlite_server.get_party(game["game_id"])
    assert party == {"game_id": game["game_id"], "location_id": "dungeon_entrance"}


def test_get_party_unknown_game(world):
    assert "error" in sqlite_server.get_party("XXXXX")


def test_move_party_through_valid_exit(world):
    game = db.create_game("Thorin", "a dwarf warrior")
    moved = sqlite_server.move_party(game["game_id"], "north")
    assert moved == {"game_id": game["game_id"], "from": "dungeon_entrance", "to": "crypt_hall"}
    assert sqlite_server.get_party(game["game_id"])["location_id"] == "crypt_hall"


def test_move_party_invalid_direction_leaves_state(world):
    game = db.create_game("Thorin", "a dwarf warrior")
    result = sqlite_server.move_party(game["game_id"], "down")
    assert "error" in result
    assert sqlite_server.get_party(game["game_id"])["location_id"] == "dungeon_entrance"


def test_games_move_independently(world):
    a = db.create_game("Thorin", "a dwarf warrior")
    b = db.create_game("Zara", "an elven wizard")
    sqlite_server.move_party(a["game_id"], "north")
    assert sqlite_server.get_party(a["game_id"])["location_id"] == "crypt_hall"
    assert sqlite_server.get_party(b["game_id"])["location_id"] == "dungeon_entrance"
