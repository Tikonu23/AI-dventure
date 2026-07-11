"""First-come-wins turn serialization: reject, don't queue."""

import threading
import time

from app import main


def _create(client, name="Thorin"):
    response = client.post(
        "/games", json={"name": name, "description": "a dwarf warrior with a battleaxe"}
    )
    return response.json()


def test_turn_rejected_while_another_in_flight(client):
    created = _create(client)
    main.active_turns[created["game_id"]] = "Thorin"
    try:
        response = client.post(
            f"/games/{created['game_id']}/turn",
            json={"token": created["player_token"], "message": "I attack!", "log_player_action": True},
        )
    finally:
        main.active_turns.pop(created["game_id"], None)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "turn_in_progress"
    assert detail["actor"] == "Thorin"


def test_turn_succeeds_once_lock_clears(client):
    created = _create(client)
    response = client.post(
        f"/games/{created['game_id']}/turn",
        json={"token": created["player_token"], "message": "I look around.", "log_player_action": True},
    )
    assert response.status_code == 200
    assert response.json()["response"]["narrative"]
    # Lock released after the turn.
    assert created["game_id"] not in main.active_turns


def test_concurrent_submission_gets_409(client, monkeypatch):
    # Generous window: the second request must reach the endpoint while the
    # first still holds the lock, including client/portal overhead. Patch via
    # main.AgentLoop — the exact class object the endpoint instantiates (a
    # `tests.conftest` import would be a different module instance under
    # pytest's conftest loading).
    monkeypatch.setattr(main.AgentLoop, "delay", 3.0)
    created = _create(client)
    game_id = created["game_id"]

    first_result = {}

    def slow_turn():
        first_result["response"] = client.post(
            f"/games/{game_id}/turn",
            json={"token": created["player_token"], "message": "I go north.", "log_player_action": True},
        )

    thread = threading.Thread(target=slow_turn)
    thread.start()
    # Wait until the first turn actually holds the lock before submitting.
    deadline = time.monotonic() + 5
    while game_id not in main.active_turns:
        assert time.monotonic() < deadline, "first turn never took the lock"
        time.sleep(0.01)

    second = client.post(
        f"/games/{game_id}/turn",
        json={"token": created["player_token"], "message": "I also act!", "log_player_action": True},
    )
    thread.join()

    assert first_result["response"].status_code == 200
    assert second.status_code == 409
