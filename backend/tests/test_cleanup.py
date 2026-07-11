"""Idle-game cleanup: 30 days after the last turn a game is deleted,
cascading its players and log rows; active games are untouched."""

import sqlite3

from app import db


def _table_count(world_db, table, game_id):
    conn = sqlite3.connect(world_db)
    try:
        return conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE game_id = ?", (game_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def test_deletes_only_idle_games_and_cascades(world_db, make_world):
    stale_world = make_world()
    stale = db.create_game("Thorin", "a dwarf warrior", stale_world)
    fresh = db.create_game("Zara", "an elven wizard", make_world())
    db.append_log(stale["game_id"], "system", "Thorin joins the party.")

    conn = sqlite3.connect(world_db)
    conn.execute(
        "UPDATE games SET last_active_at = datetime('now', '-31 days') WHERE id = ?",
        (stale["game_id"],),
    )
    conn.commit()
    conn.close()

    assert db.delete_idle_games(days=30) == 1

    assert db.get_game(stale["game_id"]) is None
    assert db.get_game(fresh["game_id"]) is not None
    assert _table_count(world_db, "game_players", stale["game_id"]) == 0
    assert _table_count(world_db, "game_log", stale["game_id"]) == 0
    assert _table_count(world_db, "game_players", fresh["game_id"]) == 1
    # The stale game's single-use world goes with it — locations and facts
    # cascade off the world row.
    assert db.get_world(stale_world["id"]) is None
    conn = sqlite3.connect(world_db)
    try:
        for table in ("locations", "npcs", "world_facts"):
            count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE world_id = ?", (stale_world["id"],)
            ).fetchone()[0]
            assert count == 0, f"{table} rows survived world deletion"
    finally:
        conn.close()


def test_thirty_day_boundary_keeps_recent_games(world_db, make_world):
    recent = db.create_game("Thorin", "a dwarf warrior", make_world())
    conn = sqlite3.connect(world_db)
    conn.execute(
        "UPDATE games SET last_active_at = datetime('now', '-29 days') WHERE id = ?",
        (recent["game_id"],),
    )
    conn.commit()
    conn.close()

    assert db.delete_idle_games(days=30) == 0
    assert db.get_game(recent["game_id"]) is not None
