"""Session-data layer: games (rooms), their players, conversation history,
and the display log. Owns the games/game_players/game_log tables in world.db;
the world tables (locations, exits, npcs) belong to the sqlite MCP server.

Everything here is plain sync sqlite3, same as the MCP server — turns are
serialized per game by main.py's active_turns gate, so contention on these
tables is rare and WAL + busy_timeout covers the rest (the MCP subprocess
writes the same file from another process).
"""

import json
import secrets
import sqlite3
import uuid
from os import environ
from pathlib import Path

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "world.db"

STARTING_LOCATION = "dungeon_entrance"

# No lookalike characters (0/O, 1/I/L, U/V) — room codes get read aloud over
# voice chat and typed on phones.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
_CODE_LENGTH = 5


def _db_path() -> Path:
    # Read the env var per-call, not at import time — tests point
    # WORLD_DB_PATH at throwaway files after this module is imported.
    return Path(environ.get("WORLD_DB_PATH", _DEFAULT_DB_PATH))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    # WAL because the MCP server subprocess writes this same file; without it
    # cross-process writes intermittently fail with "database is locked".
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create session tables. Called from app lifespan before the MCP router
    starts, since get_party/move_party read the games table."""
    conn = _connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS games (
                id TEXT PRIMARY KEY,
                location_id TEXT NOT NULL,
                history_json TEXT NOT NULL DEFAULT '[]',
                last_response_json TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_active_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS game_players (
                id TEXT PRIMARY KEY,
                game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                token TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                joined_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS game_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                -- player_id, not just name: names are user-chosen and can
                -- collide within a room, and "is this bubble mine" must not.
                player_id TEXT,
                player_name TEXT,
                text TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _sanitize_name(name: str) -> str:
    # Player names end up inside "[Name]:" attribution prefixes in the model
    # conversation — brackets/newlines would let a player spoof another
    # speaker or a system note.
    cleaned = name.replace("[", "").replace("]", "").replace("\n", " ").replace("\r", " ")
    return cleaned.strip()[:30]


def _new_room_code(conn: sqlite3.Connection) -> str:
    for _ in range(5):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
        if conn.execute("SELECT 1 FROM games WHERE id = ?", (code,)).fetchone() is None:
            return code
    raise RuntimeError("could not generate a unique room code after 5 attempts")


def _insert_player(conn: sqlite3.Connection, game_id: str, name: str, description: str) -> dict:
    player_id = uuid.uuid4().hex
    token = secrets.token_urlsafe(24)
    sanitized = _sanitize_name(name)
    conn.execute(
        "INSERT INTO game_players (id, game_id, token, name, description) VALUES (?, ?, ?, ?, ?)",
        (player_id, game_id, token, sanitized, description.strip()),
    )
    # The sanitized name goes back to the client — it's what every other
    # player will see, so the joiner's stored session must match it.
    return {"player_id": player_id, "player_token": token, "name": sanitized}


def create_game(name: str, description: str) -> dict:
    """New room + its first player, one transaction.
    Returns {game_id, player_id, player_token}."""
    conn = _connect()
    try:
        game_id = _new_room_code(conn)
        conn.execute(
            "INSERT INTO games (id, location_id) VALUES (?, ?)", (game_id, STARTING_LOCATION)
        )
        player = _insert_player(conn, game_id, name, description)
        conn.commit()
        return {"game_id": game_id, **player}
    finally:
        conn.close()


def add_player(game_id: str, name: str, description: str) -> dict | None:
    """Join an existing room. Returns {player_id, player_token}, or None if
    the game doesn't exist."""
    conn = _connect()
    try:
        if conn.execute("SELECT 1 FROM games WHERE id = ?", (game_id,)).fetchone() is None:
            return None
        player = _insert_player(conn, game_id, name, description)
        conn.commit()
        return player
    finally:
        conn.close()


def get_game(game_id: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, location_id, last_response_json, last_active_at FROM games WHERE id = ?",
            (game_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_players(game_id: str) -> list[dict]:
    conn = _connect()
    try:
        return [
            dict(r)
            for r in conn.execute(
                # rowid, not joined_at: same-second joins tie on the
                # timestamp and uuid PKs sort randomly — rowid is insert order.
                "SELECT name, description FROM game_players WHERE game_id = ? ORDER BY rowid",
                (game_id,),
            )
        ]
    finally:
        conn.close()


def get_player_by_token(game_id: str, token: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, name, description FROM game_players WHERE game_id = ? AND token = ?",
            (game_id, token),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def load_history(game_id: str) -> list:
    conn = _connect()
    try:
        row = conn.execute("SELECT history_json FROM games WHERE id = ?", (game_id,)).fetchone()
        return json.loads(row["history_json"]) if row else []
    finally:
        conn.close()


def append_history_user_message(game_id: str, text: str) -> None:
    """Append a plain user message to the stored history (join notices).
    Only safe when no turn is in flight — main.py routes mid-turn joins
    through pending_join_notices instead, because save_turn overwrites the
    whole blob at turn end."""
    conn = _connect()
    try:
        row = conn.execute("SELECT history_json FROM games WHERE id = ?", (game_id,)).fetchone()
        if row is None:
            return
        history = json.loads(row["history_json"])
        history.append({"role": "user", "content": text})
        conn.execute(
            "UPDATE games SET history_json = ? WHERE id = ?", (json.dumps(history), game_id)
        )
        conn.commit()
    finally:
        conn.close()


# Per block type, the keys the Messages API accepts as INPUT. SDK response
# blocks carry response-only extras (e.g. text blocks grew `parsed_output`)
# that the API rejects with 400 when the stored history is sent back — a
# naive model_dump() round-trip poisons the whole game.
_API_INPUT_KEYS = {
    "text": {"type", "text", "citations"},
    "tool_use": {"type", "id", "name", "input"},
    "thinking": {"type", "thinking", "signature"},
    "redacted_thinking": {"type", "data"},
}


def _api_safe_block(obj) -> dict | str:
    if not hasattr(obj, "model_dump"):
        return str(obj)
    data = obj.model_dump(exclude_none=True)
    allowed = _API_INPUT_KEYS.get(data.get("type"))
    if allowed:
        data = {k: v for k, v in data.items() if k in allowed}
    return data


def save_turn(game_id: str, history: list, structured_json: str, log_entries: list[dict]) -> int:
    """Persist a completed turn in one transaction: full history blob, last
    structured response, display-log rows, and the idle-cleanup clock.
    Returns the last inserted game_log id (the frontend dedupes replayed
    turn_complete events against it on reconnect).

    History entries contain Anthropic SDK pydantic content blocks —
    serialized down to the API's input shape so they round-trip cleanly.
    """
    history_json = json.dumps(history, default=_api_safe_block)
    conn = _connect()
    try:
        conn.execute(
            "UPDATE games SET history_json = ?, last_response_json = ?, "
            "last_active_at = datetime('now') WHERE id = ?",
            (history_json, structured_json, game_id),
        )
        last_id = 0
        for entry in log_entries:
            cursor = conn.execute(
                "INSERT INTO game_log (game_id, role, player_id, player_name, text) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    game_id,
                    entry["role"],
                    entry.get("player_id"),
                    entry.get("player_name"),
                    entry["text"],
                ),
            )
            last_id = cursor.lastrowid
        conn.commit()
        return last_id
    finally:
        conn.close()


def append_log(game_id: str, role: str, text: str, player_name: str | None = None) -> int:
    """Single display-log row outside a turn (e.g. '{name} joins the party.')."""
    conn = _connect()
    try:
        cursor = conn.execute(
            "INSERT INTO game_log (game_id, role, player_name, text) VALUES (?, ?, ?, ?)",
            (game_id, role, player_name, text),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def load_log(game_id: str) -> tuple[list[dict], int]:
    """Returns (entries, last_log_id) — last_log_id is 0 for an empty log."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, role, player_id, player_name, text FROM game_log "
            "WHERE game_id = ? ORDER BY id",
            (game_id,),
        ).fetchall()
        entries = [
            {
                "role": r["role"],
                "player_id": r["player_id"],
                "player_name": r["player_name"],
                "text": r["text"],
            }
            for r in rows
        ]
        return entries, (rows[-1]["id"] if rows else 0)
    finally:
        conn.close()


def delete_idle_games(days: int = 30) -> int:
    """Delete games idle past the cutoff; cascades players and log rows.
    Returns how many games were deleted."""
    conn = _connect()
    try:
        cursor = conn.execute(
            "DELETE FROM games WHERE last_active_at < datetime('now', ?)", (f"-{days} days",)
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()
