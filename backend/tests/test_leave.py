"""Leaving a game: the character is removed from the roster (with the model
notified via history and the room via log + broadcast), and the last player
out deletes the game and its single-use world."""

from app import db


def _create(client, name="Thorin"):
    response = client.post(
        "/games", json={"name": name, "description": "a dwarf warrior with a battleaxe"}
    )
    return response.json()


def _join(client, game_id, name="Mira"):
    response = client.post(
        f"/games/{game_id}/join", json={"name": name, "description": "a wizard of the old order"}
    )
    return response.json()


def test_leave_removes_player_and_notifies(client):
    created = _create(client)
    game_id = created["game_id"]
    joiner = _join(client, game_id)

    response = client.post(f"/games/{game_id}/leave", json={"token": joiner["player_token"]})
    assert response.status_code == 200

    assert [p["name"] for p in db.list_players(game_id)] == ["Thorin"]
    entries, _ = db.load_log(game_id)
    assert any(e["text"] == "Mira leaves the party." for e in entries)
    # The model hears about it next turn.
    assert any(
        "Mira leaves the party" in m["content"]
        for m in db.load_history(game_id)
        if isinstance(m["content"], str)
    )


def test_last_player_leaving_deletes_game_and_world(client):
    created = _create(client)
    game_id = created["game_id"]
    world_id = db.get_game(game_id)["world_id"]

    response = client.post(f"/games/{game_id}/leave", json={"token": created["player_token"]})
    assert response.status_code == 200
    assert db.get_game(game_id) is None
    assert db.get_world(world_id) is None


def test_leave_requires_valid_token(client):
    created = _create(client)
    response = client.post(f"/games/{created['game_id']}/leave", json={"token": "bogus"})
    assert response.status_code == 403
