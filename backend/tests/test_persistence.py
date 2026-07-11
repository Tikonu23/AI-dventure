"""Games survive restarts: everything a turn produces round-trips through
SQLite, including Anthropic SDK pydantic content blocks in the history."""

import sqlite3

from pydantic import BaseModel

from app import db


def _create(client):
    return client.post(
        "/games", json={"name": "Thorin", "description": "a dwarf warrior"}
    ).json()


def _run_turn(client, created, message="I look around."):
    return client.post(
        f"/games/{created['game_id']}/turn",
        json={"token": created["player_token"], "message": message, "log_player_action": True},
    )


def test_turn_persists_history_log_and_response(client, world_db):
    created = _create(client)
    assert _run_turn(client, created).status_code == 200
    game_id = created["game_id"]

    # History round-trips as plain dicts — including the assistant entry
    # whose content held a pydantic model before serialization.
    history = db.load_history(game_id)
    assert history[-2] == {"role": "user", "content": "[Thorin]: I look around."}
    assert history[-1]["role"] == "assistant"
    assert isinstance(history[-1]["content"][0], dict)
    assert history[-1]["content"][0]["narrative"] == "The dark presses in around the party."

    log_entries, last_log_id = db.load_log(game_id)
    assert last_log_id > 0
    assert [(e["role"], e["player_name"]) for e in log_entries] == [
        ("player", "Thorin"),
        ("narrator", None),
    ]
    assert log_entries[0]["text"] == "I look around."
    # player_id rides along so clients can style own-vs-teammate bubbles.
    assert log_entries[0]["player_id"] == created["player_id"]
    assert log_entries[1]["player_id"] is None

    game = db.get_game(game_id)
    assert game["last_response_json"] is not None


def test_turn_advances_last_active_at(client, world_db):
    created = _create(client)
    game_id = created["game_id"]
    # Backdate so the datetime('now') update is observable regardless of
    # second-resolution timestamps.
    conn = sqlite3.connect(world_db)
    conn.execute(
        "UPDATE games SET last_active_at = datetime('now', '-2 days') WHERE id = ?", (game_id,)
    )
    conn.commit()
    before = conn.execute(
        "SELECT last_active_at FROM games WHERE id = ?", (game_id,)
    ).fetchone()[0]
    conn.close()

    assert _run_turn(client, created).status_code == 200

    after = db.get_game(game_id)["last_active_at"]
    assert after > before


def test_history_strips_response_only_block_fields(world_db):
    # SDK text blocks carry response-only extras (parsed_output) — sending
    # them back as input is a 400 from the API. Regression: a game bricked
    # after its first persisted turn because every later turn failed on this.
    class SdkTextBlock(BaseModel):
        type: str = "text"
        text: str = "The dark presses in."
        parsed_output: str | None = "should not survive"
        citations: list | None = None

    game = db.create_game("Thorin", "a dwarf warrior")
    history = [{"role": "assistant", "content": [SdkTextBlock()]}]
    db.save_turn(game["game_id"], history, "{}", [])

    block = db.load_history(game["game_id"])[0]["content"][0]
    assert block == {"type": "text", "text": "The dark presses in."}


def test_opening_turn_is_not_logged_as_player_action(client, world_db):
    created = _create(client)
    response = client.post(
        f"/games/{created['game_id']}/turn",
        json={
            "token": created["player_token"],
            "message": "Begin the adventure.",
            "log_player_action": False,
        },
    )
    assert response.status_code == 200

    log_entries, _ = db.load_log(created["game_id"])
    assert [e["role"] for e in log_entries] == ["narrator"]
    # And the action reached the model unattributed — a stage direction, not
    # a character's utterance.
    history = db.load_history(created["game_id"])
    assert history[0] == {"role": "user", "content": "Begin the adventure."}
