"""World validation and the ready-world pool. The validator is what stands
between a plausible-looking generation and a soft-locked game, so the broken
shapes it must catch each get a case."""

import copy

import pytest

from app import db
from app.worldgen import FALLBACK_WORLD, WorldValidationError, validate_world


def _world(**overrides) -> dict:
    world = copy.deepcopy(FALLBACK_WORLD)
    world.update(overrides)
    return world


def _expect_error(world: dict, fragment: str) -> None:
    with pytest.raises(WorldValidationError) as excinfo:
        validate_world(world)
    assert any(fragment in e for e in excinfo.value.errors), excinfo.value.errors


def test_fallback_world_is_valid():
    validate_world(FALLBACK_WORLD)


def test_rejects_duplicate_slug():
    world = _world()
    world["npcs"][0]["id"] = "ossuary"  # collides with a location slug
    _expect_error(world, "duplicate slug")


def test_rejects_bad_slug():
    world = _world()
    world["locations"][0]["id"] = "Dungeon Entrance!"
    _expect_error(world, "bad slug")


def test_rejects_unknown_starting_location():
    _expect_error(_world(starting_location="nowhere"), "starting_location")


def test_rejects_dangling_exit():
    world = _world()
    world["locations"][0]["exits"].append({"direction": "west", "to": "the_void"})
    _expect_error(world, "unknown location 'the_void'")


def test_rejects_unreachable_location():
    world = _world()
    world["locations"].append(
        {"id": "sealed_vault", "name": "Sealed Vault", "description": "x", "exits": []}
    )
    _expect_error(world, "unreachable")


def test_rejects_soft_lock_room():
    # A room you can enter but never leave must fail validation — the party
    # would be stranded forever.
    world = _world()
    world["locations"].append(
        {"id": "oubliette", "name": "The Oubliette", "description": "x", "exits": []}
    )
    world["locations"][2]["exits"].append({"direction": "east", "to": "oubliette"})
    _expect_error(world, "cannot return")


def test_rejects_duplicate_direction():
    world = _world()
    world["locations"][1]["exits"].append({"direction": "south", "to": "ossuary"})
    _expect_error(world, "two 'south' exits")


def test_rejects_npc_in_unknown_location():
    world = _world()
    world["npcs"][0]["location"] = "nowhere"
    _expect_error(world, "unknown location 'nowhere'")


def test_rejects_fact_against_unknown_entity():
    world = _world()
    world["facts"].append({"entity": "ghost", "key": "k", "value": "v"})
    _expect_error(world, "unknown entity 'ghost'")


def test_accepts_world_level_fact():
    world = _world()
    world["facts"].append({"entity": "world", "key": "curse", "value": "the dawn never comes"})
    validate_world(world)


def test_rejects_missing_resolution():
    world = _world()
    del world["resolution"]
    _expect_error(world, "resolution steps")


def test_rejects_too_few_resolution_steps():
    world = _world()
    world["resolution"]["steps"] = world["resolution"]["steps"][:1]
    _expect_error(world, "resolution steps, need")


def test_two_step_journey_needs_two_places():
    world = _world()
    world["resolution"]["steps"] = world["resolution"]["steps"][:2]
    validate_world(world)  # two steps, two anchors — fine
    world["resolution"]["steps"][1]["anchor"] = world["resolution"]["steps"][0]["anchor"]
    _expect_error(world, "need at least 2")


def test_rejects_resolution_step_with_unknown_anchor():
    world = _world()
    world["resolution"]["steps"][0]["anchor"] = "nowhere"
    _expect_error(world, "unknown entity 'nowhere'")


def test_rejects_clustered_resolution_steps():
    # All steps in one place is a tripwire, not a journey.
    world = _world()
    for step in world["resolution"]["steps"]:
        step["anchor"] = "ossuary"
    _expect_error(world, "need at least 3")


def test_rejects_resolution_piled_on_starting_location():
    world = _world()
    world["resolution"]["steps"][0]["anchor"] = "dungeon_entrance"
    world["resolution"]["steps"][1]["anchor"] = "dungeon_entrance"
    _expect_error(world, "starting location")


def test_insert_prefixes_ids_and_maps_facts(world_db):
    world_id = db.insert_world(FALLBACK_WORLD)
    world = db.get_world(world_id)
    assert world["starting_location_id"] == f"{world_id}:dungeon_entrance"

    import sqlite3

    conn = sqlite3.connect(world_db)
    try:
        location_ids = {r[0] for r in conn.execute("SELECT id FROM locations WHERE world_id = ?", (world_id,))}
        assert location_ids == {
            f"{world_id}:{s}"
            for s in ("dungeon_entrance", "crypt_hall", "ossuary", "sunken_chapel")
        }
        exit_targets = {r[0] for r in conn.execute("SELECT to_location_id FROM exits WHERE world_id = ?", (world_id,))}
        assert exit_targets <= location_ids
        fact_entities = {r[0] for r in conn.execute("SELECT entity_id FROM world_facts WHERE world_id = ?", (world_id,))}
        assert fact_entities == {f"{world_id}:collector", f"{world_id}:ossuary", f"{world_id}:aldric"}
        # Resolution anchors get world-qualified too.
        import json

        resolution = json.loads(
            conn.execute(
                "SELECT resolution_json FROM worlds WHERE id = ?", (world_id,)
            ).fetchone()[0]
        )
        assert [s["anchor"] for s in resolution["steps"]] == [
            f"{world_id}:aldric",
            f"{world_id}:ossuary",
            f"{world_id}:sunken_chapel",
        ]
    finally:
        conn.close()


def test_pool_claim_lifecycle(world_db):
    assert db.ready_world_count() == 0
    assert db.claim_world() is None

    first = db.insert_world(FALLBACK_WORLD)
    second = db.insert_world(FALLBACK_WORLD)
    assert db.ready_world_count() == 2

    claimed = db.claim_world()
    assert claimed["id"] == first  # oldest first
    assert db.ready_world_count() == 1
    assert db.get_world(first)["status"] == "claimed"

    assert db.claim_world()["id"] == second
    assert db.claim_world() is None
