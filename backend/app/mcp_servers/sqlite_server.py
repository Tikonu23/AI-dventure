"""MCP server exposing world state (locations, exits, NPCs, players) backed
by a SQLite file. This is the only thing allowed to touch world.db — Claude
never queries SQLite directly, only through these tools.

Run standalone via stdio: `python -m app.mcp_servers.sqlite_server`
"""

import os
import sqlite3
from pathlib import Path

from mcp.server.fastmcp import FastMCP

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "world.db"
DB_PATH = Path(os.environ.get("WORLD_DB_PATH", _DEFAULT_DB_PATH))

mcp = FastMCP("sqlite")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS locations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS exits (
            location_id TEXT NOT NULL,
            direction TEXT NOT NULL,
            to_location_id TEXT NOT NULL,
            PRIMARY KEY (location_id, direction)
        );
        CREATE TABLE IF NOT EXISTS npcs (
            id TEXT PRIMARY KEY,
            location_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS players (
            id TEXT PRIMARY KEY,
            location_id TEXT NOT NULL
        );
        """
    )
    if conn.execute("SELECT COUNT(*) FROM locations").fetchone()[0] == 0:
        _seed(conn)
    conn.commit()


def _seed(conn: sqlite3.Connection) -> None:
    """One dungeon entrance + a handful of rooms, two NPCs — Phase 1 scope."""
    conn.executemany(
        "INSERT INTO locations (id, name, description) VALUES (?, ?, ?)",
        [
            (
                "dungeon_entrance",
                "The Ruined Gate",
                "A broken portcullis hangs from rusted chains. Cold air "
                "breathes up from the dark beyond, carrying the smell of "
                "wet stone and something long dead.",
            ),
            (
                "crypt_hall",
                "Crypt Hall",
                "Rows of shattered sarcophagi line a hall lit by a single "
                "guttering torch. Something has been dragging itself "
                "across the dust here, recently.",
            ),
            (
                "ossuary",
                "The Ossuary",
                "Bones are stacked floor to ceiling in deliberate, "
                "unsettling patterns. A low hum, felt more than heard, "
                "comes from somewhere beneath the floor.",
            ),
        ],
    )
    conn.executemany(
        "INSERT INTO exits (location_id, direction, to_location_id) VALUES (?, ?, ?)",
        [
            ("dungeon_entrance", "north", "crypt_hall"),
            ("crypt_hall", "south", "dungeon_entrance"),
            ("crypt_hall", "east", "ossuary"),
            ("ossuary", "west", "crypt_hall"),
        ],
    )
    conn.executemany(
        "INSERT INTO npcs (id, location_id, name, description) VALUES (?, ?, ?, ?)",
        [
            (
                "aldric",
                "crypt_hall",
                "Brother Aldric",
                "A monk driven mad by what he found down here. He mutters "
                "scripture that isn't quite scripture anymore.",
            ),
            (
                "collector",
                "ossuary",
                "The Collector",
                "A hooded figure arranging bones with obsessive care. "
                "It does not look up when you enter.",
            ),
        ],
    )
    conn.execute(
        "INSERT INTO players (id, location_id) VALUES (?, ?)",
        ("p1", "dungeon_entrance"),
    )


# Runs at import time so schema/seed exist before the first tool call this
# subprocess receives — connection is per-call below, not held open.
_startup_conn = _connect()
_init_db(_startup_conn)
_startup_conn.close()


@mcp.tool()
def get_location(location_id: str) -> dict:
    """Retrieve a location's name, description, exits, and NPCs present."""
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
        }
    finally:
        conn.close()


@mcp.tool()
def get_npc(npc_id: str) -> dict:
    """Retrieve an NPC's name and description by ID."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, name, description FROM npcs WHERE id = ?", (npc_id,)
        ).fetchone()
        if row is None:
            return {"error": f"unknown npc '{npc_id}'"}
        return dict(row)
    finally:
        conn.close()


@mcp.tool()
def get_player(player_id: str) -> dict:
    """Retrieve a player's current location ID."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, location_id FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        if row is None:
            return {"error": f"unknown player '{player_id}'"}
        return dict(row)
    finally:
        conn.close()


@mcp.tool()
def move_player(player_id: str, direction: str) -> dict:
    """Move a player through an exit from their current location.

    Fails with an error if there is no exit in that direction — the caller
    (Claude) should narrate that as a blocked path, not invent a new room.
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT location_id FROM players WHERE id = ?", (player_id,)
        ).fetchone()
        if row is None:
            return {"error": f"unknown player '{player_id}'"}
        current = row["location_id"]
        exit_row = conn.execute(
            "SELECT to_location_id FROM exits WHERE location_id = ? AND direction = ?",
            (current, direction),
        ).fetchone()
        if exit_row is None:
            return {"error": f"no exit '{direction}' from '{current}'"}
        new_location = exit_row["to_location_id"]
        conn.execute(
            "UPDATE players SET location_id = ? WHERE id = ?", (new_location, player_id)
        )
        conn.commit()
        return {"player": player_id, "from": current, "to": new_location}
    finally:
        conn.close()


if __name__ == "__main__":
    mcp.run(transport="stdio")
