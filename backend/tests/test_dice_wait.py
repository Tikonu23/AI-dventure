"""Player-clicked dice: a pending roll blocks the turn until POST /roll
releases it, /state exposes it for reconnects, a click with nothing pending
is rejected, and persisted roll rows round-trip as objects."""

import asyncio
import json

from app import db, main


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


def test_roll_log_rows_round_trip_as_objects(client):
    created = _create(client)
    game_id = created["game_id"]
    payload = {"expression": "1d20+2", "rolls": [15], "modifier": 2, "total": 17}
    db.append_log(game_id, "narrator", "The blade hovers.")
    db.append_log(game_id, "roll", json.dumps(payload))

    state = client.get(
        f"/games/{game_id}/state", params={"token": created["player_token"]}
    ).json()
    roll_rows = [e for e in state["log"] if e["role"] == "roll"]
    assert roll_rows and roll_rows[0]["roll"] == payload


def test_roll_requires_valid_token(client):
    created = _create(client)
    response = client.post(f"/games/{created['game_id']}/roll", json={"token": "bogus"})
    assert response.status_code == 403
