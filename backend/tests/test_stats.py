"""Player stats and game endings: adjust_player_stats clamps in code, death
is permanent, the last death flips the game to lost mechanically,
complete_game flips it to won, and ended games / dead players take no
more turns."""

import os
import sqlite3

import pytest

from app import db
from app.mcp_servers import sqlite_server


@pytest.fixture
def world(world_db, make_world, monkeypatch):
    monkeypatch.setattr(sqlite_server, "DB_PATH", world_db)
    return make_world()


def test_adjust_clamps_to_bounds_and_flags_death(world):
    game = db.create_game("Thorin", "a dwarf warrior", world)
    game_id = game["game_id"]

    hit = sqlite_server.adjust_player_stats(game_id, "Thorin", hp_delta=-30, mana_delta=-10)
    assert (hit["hp"], hit["mana"], hit["dead"]) == (70, 90, False)

    # Healing never exceeds max; spending never goes below zero.
    over = sqlite_server.adjust_player_stats(game_id, "Thorin", hp_delta=999, mana_delta=-999)
    assert (over["hp"], over["mana"]) == (100, 0)

    dead = sqlite_server.adjust_player_stats(game_id, "Thorin", hp_delta=-150)
    assert dead["dead"] is True and dead["hp"] == 0


def test_dead_players_cannot_be_adjusted(world):
    game = db.create_game("Thorin", "a dwarf warrior", world)
    sqlite_server.adjust_player_stats(game["game_id"], "Thorin", hp_delta=-100)
    revive = sqlite_server.adjust_player_stats(game["game_id"], "Thorin", hp_delta=50)
    assert "error" in revive


def test_last_death_loses_the_game_mechanically(world):
    game = db.create_game("Thorin", "a dwarf warrior", world)
    game_id = game["game_id"]
    db.add_player(game_id, "Mira", "a wizard")

    first = sqlite_server.adjust_player_stats(game_id, "Thorin", hp_delta=-100)
    assert first["dead"] is True and first["game_lost"] is False
    assert db.get_game(game_id)["status"] == "active"

    last = sqlite_server.adjust_player_stats(game_id, "Mira", hp_delta=-100)
    assert last["game_lost"] is True
    assert db.get_game(game_id)["status"] == "lost"


def test_complete_game_wins_once(world):
    game = db.create_game("Thorin", "a dwarf warrior", world)
    # The fixture world has a 3-step resolution — walk the journey first
    # (the gate itself is covered in test_journey.py).
    for step in range(3):
        sqlite_server.complete_resolution_step(game["game_id"], step)
    assert sqlite_server.complete_game(game["game_id"])["status"] == "won"
    assert db.get_game(game["game_id"])["status"] == "won"
    assert "error" in sqlite_server.complete_game(game["game_id"])


def test_get_party_includes_player_state(world):
    game = db.create_game("Thorin", "a dwarf warrior", world)
    party = sqlite_server.get_party(game["game_id"])
    assert party["players"] == [
        {"name": "Thorin", "hp": 100, "max_hp": 100, "mana": 100, "max_mana": 100, "dead": False}
    ]


def _set_hp(game_id: str, name: str, hp: int) -> None:
    conn = sqlite3.connect(os.environ["WORLD_DB_PATH"])
    conn.execute(
        "UPDATE game_players SET hp = ? WHERE game_id = ? AND name = ?", (hp, game_id, name)
    )
    conn.commit()
    conn.close()


def test_dead_player_cannot_take_turns(client):
    created = client.post(
        "/games", json={"name": "Thorin", "description": "a dwarf warrior"}
    ).json()
    _set_hp(created["game_id"], "Thorin", 0)
    response = client.post(
        f"/games/{created['game_id']}/turn",
        json={"token": created["player_token"], "message": "I rise!", "log_player_action": True},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "player_dead"


def test_ended_game_takes_no_turns_and_reports_status(client):
    created = client.post(
        "/games", json={"name": "Thorin", "description": "a dwarf warrior"}
    ).json()
    game_id = created["game_id"]
    conn = sqlite3.connect(os.environ["WORLD_DB_PATH"])
    conn.execute("UPDATE games SET status = 'won' WHERE id = ?", (game_id,))
    conn.commit()
    conn.close()

    state = client.get(f"/games/{game_id}/state", params={"token": created["player_token"]}).json()
    assert state["status"] == "won"
    assert state["players"][0]["hp"] == 100

    response = client.post(
        f"/games/{game_id}/turn",
        json={"token": created["player_token"], "message": "More!", "log_player_action": True},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "game_over"
