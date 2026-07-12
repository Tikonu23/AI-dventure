"""World choice at game creation: GET /worlds lists the ready pool, POST
/games with world_id claims exactly that world, and a stolen/unknown world
is an honest 409 (not a silent substitute)."""

import copy

from app import db, worldgen


def _ready_world(title: str) -> str:
    payload = copy.deepcopy(worldgen.FALLBACK_WORLD)
    payload["title"] = title
    return db.insert_world(payload)  # default status='ready'


def test_worlds_endpoint_lists_ready_pool(client):
    world_id = _ready_world("The Hollow Spire")
    listed = client.get("/worlds").json()
    mine = next(w for w in listed if w["id"] == world_id)
    assert mine["title"] == "The Hollow Spire"
    assert mine["concept"]


def test_create_with_world_id_claims_that_world(client):
    world_id = _ready_world("The Hollow Spire")
    response = client.post(
        "/games",
        json={"name": "Thorin", "description": "a dwarf warrior", "world_id": world_id},
    )
    assert response.status_code == 200
    game = db.get_game(response.json()["game_id"])
    assert game["world_id"] == world_id
    assert db.get_world(world_id)["status"] == "claimed"


def test_create_with_taken_world_is_409(client):
    world_id = db.insert_world(copy.deepcopy(worldgen.FALLBACK_WORLD), status="claimed")
    response = client.post(
        "/games",
        json={"name": "Thorin", "description": "a dwarf warrior", "world_id": world_id},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "world_taken"
