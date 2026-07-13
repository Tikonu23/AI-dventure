"""MCP server exposing world state (locations, exits, NPCs, party position,
pre-authored facts) backed by a SQLite file. This is the only thing allowed
to MUTATE world state during play — Claude never queries SQLite directly,
only through these tools. All DDL is owned by app.db (worlds are written
there by the generation pipeline, at world-gen time, never during a turn);
entity ids are globally unique (world-prefixed), so tools stay single-id.

Run standalone via stdio: `python -m app.mcp_servers.sqlite_server`
"""

import os
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from app import db as app_db

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "world.db"
DB_PATH = Path(os.environ.get("WORLD_DB_PATH", _DEFAULT_DB_PATH))

mcp = FastMCP("sqlite")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # WAL because the FastAPI process (app.db) writes this same file from
    # another process; without it cross-process writes intermittently fail
    # with "database is locked".
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# Schema init at import time so tables exist before the first tool call this
# subprocess receives. All DDL lives in app.db; worlds themselves are
# inserted by the generation pipeline in the app process, never here.
app_db.init_db()


def _facts_for(conn: sqlite3.Connection, entity_id: str) -> dict:
    return {
        r["key"]: r["value"]
        for r in conn.execute(
            "SELECT key, value FROM world_facts WHERE entity_id = ?", (entity_id,)
        )
    }


@mcp.tool()
def get_location(location_id: str) -> dict:
    """Returns {id, name, description, exits, npcs, facts} — exits maps
    direction to the destination location_id; npcs is a list of
    {id, name, description}; facts are SECRET pre-authored truths about this
    place (hidden doors, dangers, how things really work) — enforce them as
    ground truth but never reveal them outright; let players discover them.
    Returns {"error": ...} if location_id doesn't exist."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, name, description FROM locations WHERE id = ?", (location_id,)
        ).fetchone()
        if row is None:
            return {"error": f"unknown location '{location_id}'"}
        exits = {
            r["direction"]: r["to_location_id"]
            for r in conn.execute(
                "SELECT direction, to_location_id FROM exits WHERE location_id = ?",
                (location_id,),
            )
        }
        npcs = [
            dict(r)
            for r in conn.execute(
                "SELECT id, name, description FROM npcs WHERE location_id = ?",
                (location_id,),
            )
        ]
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "exits": exits,
            "npcs": npcs,
            "facts": _facts_for(conn, location_id),
        }
    finally:
        conn.close()


@mcp.tool()
def get_npc(npc_id: str) -> dict:
    """Returns {id, location_id, name, description, facts}. facts are SECRET
    pre-authored truths about this NPC (what they hide, want, or fear) —
    enforce them as ground truth but never reveal them outright.
    Returns {"error": ...} if npc_id doesn't exist."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, location_id, name, description FROM npcs WHERE id = ?", (npc_id,)
        ).fetchone()
        if row is None:
            return {"error": f"unknown npc '{npc_id}'"}
        return {**dict(row), "facts": _facts_for(conn, npc_id)}
    finally:
        conn.close()


@mcp.tool()
def get_party(game_id: str) -> dict:
    """Returns {game_id, location_id, players} — the party's current position
    (the whole party shares one location) and each member's current state:
    {name, hp, max_hp, mana, max_mana, dead}. Returns {"error": ...} if
    game_id doesn't exist."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, location_id FROM games WHERE id = ?", (game_id,)
        ).fetchone()
        if row is None:
            return {"error": f"unknown game '{game_id}'"}
        players = [
            {**dict(r), "dead": r["hp"] == 0}
            for r in conn.execute(
                "SELECT name, hp, max_hp, mana, max_mana FROM game_players "
                "WHERE game_id = ? ORDER BY rowid",
                (game_id,),
            )
        ]
        return {"game_id": row["id"], "location_id": row["location_id"], "players": players}
    finally:
        conn.close()


@mcp.tool()
def adjust_player_stats(game_id: str, player_name: str, hp_delta: int = 0, mana_delta: int = 0) -> dict:
    """Apply damage, healing, mana spend, or mana recovery to one party
    member. Negative deltas subtract (damage / casting cost), positive add
    (healing / rest). Values are clamped to 0..max in code — narrate ONLY
    the numbers this returns. At 0 HP the character is dead, permanently:
    the dead cannot be healed or act. If this kills the last living member,
    the game is lost (game_lost: true) — narrate the party's end.
    Returns {player, hp, max_hp, mana, max_mana, dead, game_lost}."""
    conn = _connect()
    try:
        row = conn.execute(
            # ponytail: matched by name — names aren't guaranteed unique in a
            # room; switch to ids if that ever bites (same note as the UI).
            "SELECT id, hp, max_hp, mana, max_mana FROM game_players "
            "WHERE game_id = ? AND name = ?",
            (game_id, player_name),
        ).fetchone()
        if row is None:
            return {"error": f"no player named '{player_name}' in game '{game_id}'"}
        if row["hp"] == 0:
            return {"error": f"{player_name} is dead — the dead cannot be healed or harmed"}

        hp = max(0, min(row["max_hp"], row["hp"] + hp_delta))
        mana = max(0, min(row["max_mana"], row["mana"] + mana_delta))
        conn.execute(
            "UPDATE game_players SET hp = ?, mana = ? WHERE id = ?", (hp, mana, row["id"])
        )

        # Loss is mechanical, not model judgment: last living member at 0 HP
        # flips the game in the same transaction the death happened in.
        game_lost = False
        if hp == 0:
            alive = conn.execute(
                "SELECT COUNT(*) FROM game_players WHERE game_id = ? AND hp > 0", (game_id,)
            ).fetchone()[0]
            if alive == 0:
                conn.execute(
                    "UPDATE games SET status = 'lost' WHERE id = ? AND status = 'active'",
                    (game_id,),
                )
                game_lost = True
        conn.commit()
        return {
            "player": player_name,
            "hp": hp,
            "max_hp": row["max_hp"],
            "mana": mana,
            "max_mana": row["max_mana"],
            "dead": hp == 0,
            "game_lost": game_lost,
        }
    finally:
        conn.close()


@mcp.tool()
def complete_game(game_id: str) -> dict:
    """Declare the campaign WON. Call this exactly once, only when the
    world's pre-authored 'resolution' fact has genuinely been satisfied —
    then narrate the ending. No further turns can be taken afterward."""
    conn = _connect()
    try:
        cursor = conn.execute(
            "UPDATE games SET status = 'won' WHERE id = ? AND status = 'active'", (game_id,)
        )
        conn.commit()
        if cursor.rowcount == 0:
            return {"error": f"game '{game_id}' does not exist or has already ended"}
        return {"game_id": game_id, "status": "won"}
    finally:
        conn.close()


@mcp.tool()
def move_party(game_id: str, direction: str) -> dict:
    """Move the whole party through an exit from its current location — the
    party always travels as a single unit.

    Fails with an error if there is no exit in that direction — the caller
    (Claude) should narrate that as a blocked path, not invent a new room.
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT location_id FROM games WHERE id = ?", (game_id,)
        ).fetchone()
        if row is None:
            return {"error": f"unknown game '{game_id}'"}
        current = row["location_id"]
        exit_row = conn.execute(
            "SELECT to_location_id FROM exits WHERE location_id = ? AND direction = ?",
            (current, direction),
        ).fetchone()
        if exit_row is None:
            return {"error": f"no exit '{direction}' from '{current}'"}
        new_location = exit_row["to_location_id"]
        conn.execute(
            "UPDATE games SET location_id = ? WHERE id = ?", (new_location, game_id)
        )
        conn.commit()
        return {"game_id": game_id, "from": current, "to": new_location}
    finally:
        conn.close()


if __name__ == "__main__":
    mcp.run(transport="stdio")
