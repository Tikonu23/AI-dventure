"""Player-clicked dice: a pending roll blocks the turn until POST /roll
releases it, /state exposes it for reconnects, and a click with nothing
pending is rejected."""

import asyncio

from app import main


def _create(client, name="Thorin"):
    response = client.post(
        "/games", json={"name": name, "description": "a dwarf warrior with a battleaxe"}
    )
    return response.json()


def test_roll_releases_pending_wait_and_state_exposes_it(client):
    created = _create(client)
    game_id = created["game_id"]
    release = asyncio.Event()
    main.pending_rolls[game_id] = (release, "1d20+5")
    try:
        state = client.get(
            f"/games/{game_id}/state", params={"token": created["player_token"]}
        ).json()
        assert state["pending_roll"] == "1d20+5"

        response = client.post(f"/games/{game_id}/roll", json={"token": created["player_token"]})
        assert response.status_code == 200
        assert release.is_set()
    finally:
        main.pending_rolls.pop(game_id, None)


def test_roll_with_nothing_pending_is_409(client):
    created = _create(client)
    response = client.post(
        f"/games/{created['game_id']}/roll", json={"token": created["player_token"]}
    )
    assert response.status_code == 409


def test_roll_requires_valid_token(client):
    created = _create(client)
    response = client.post(f"/games/{created['game_id']}/roll", json={"token": "bogus"})
    assert response.status_code == 403
