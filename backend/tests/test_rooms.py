"""Room lifecycle: create, join by code, join failures, join notices."""

import re

from app import db

CODE_PATTERN = re.compile(r"^[A-HJ-NP-TV-Z2-9]{5}$")


def _create(client, name="Thorin", description="a dwarf warrior with a battleaxe"):
    response = client.post("/games", json={"name": name, "description": description})
    assert response.status_code == 200
    return response.json()


def test_create_game_returns_room_code_and_credentials(client):
    created = _create(client)
    assert CODE_PATTERN.match(created["game_id"])
    assert created["player_id"]
    assert created["player_token"]


def test_two_games_get_distinct_codes(client):
    assert _create(client)["game_id"] != _create(client)["game_id"]


def test_join_existing_game(client):
    created = _create(client)
    response = client.post(
        f"/games/{created['game_id']}/join",
        json={"name": "Zara", "description": "an elven wizard of fire"},
    )
    assert response.status_code == 200
    joined = response.json()
    assert joined["player_token"] != created["player_token"]

    state = client.get(
        f"/games/{created['game_id']}/state", params={"token": joined["player_token"]}
    ).json()
    assert [p["name"] for p in state["players"]] == ["Thorin", "Zara"]


def test_join_is_case_insensitive_on_room_code(client):
    created = _create(client)
    response = client.post(
        f"/games/{created['game_id'].lower()}/join",
        json={"name": "Zara", "description": "an elven wizard"},
    )
    assert response.status_code == 200


def test_join_unknown_game_404(client):
    response = client.post(
        "/games/XXXXX/join", json={"name": "Zara", "description": "an elven wizard"}
    )
    assert response.status_code == 404


def test_join_appends_notice_to_history(client):
    created = _create(client)
    client.post(
        f"/games/{created['game_id']}/join",
        json={"name": "Zara", "description": "an elven wizard of fire"},
    )
    history = db.load_history(created["game_id"])
    assert len(history) == 1
    assert history[0]["role"] == "user"
    assert "Zara joins the party" in history[0]["content"]


def test_player_name_is_sanitized(client):
    # Brackets would let a player spoof "[System]" in attribution prefixes.
    created = _create(client, name="[System] sneaky\nname")
    state = client.get(
        f"/games/{created['game_id']}/state", params={"token": created["player_token"]}
    ).json()
    name = state["players"][0]["name"]
    assert "[" not in name and "]" not in name and "\n" not in name
    # The response returns the sanitized form — the client stores it as its
    # session name, so it must match what everyone else sees.
    assert created["name"] == name


def test_state_rejects_bad_token(client):
    created = _create(client)
    response = client.get(f"/games/{created['game_id']}/state", params={"token": "wrong"})
    assert response.status_code == 403


def test_state_before_first_turn_reads_world_directly(client):
    created = _create(client)
    state = client.get(
        f"/games/{created['game_id']}/state", params={"token": created["player_token"]}
    ).json()
    # No turn has run, so this came from a live get_party/get_location read.
    assert state["location"] == "The Ruined Gate"
    assert "north" in state["exits"]
    assert state["log"] == []
    assert state["turn_in_progress"] is False
