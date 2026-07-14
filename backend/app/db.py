"""Data layer for world.db: generated worlds (with their locations, exits,
NPCs, and pre-authored facts), the ready-world pool, games (rooms), players,
conversation history, and the display log. Owns ALL table DDL — the sqlite
MCP server only reads/mutates through it.

Everything here is plain sync sqlite3, same as the MCP server — turns are
serialized per game by main.py's active_turns gate, so contention on these
tables is rare and WAL + busy_timeout covers the rest (the MCP subprocess
writes the same file from another process).

Entity ids are made globally unique by prefixing the world id onto the
generator's slugs ("a1b2c3:crypt_hall"), so tools like get_location keep
their single-id signature with no cross-world collisions or scoping params.
"""

import json
import secrets
import sqlite3
import uuid
from os import environ
from pathlib import Path

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "world.db"

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
    """Create all tables. Called from app lifespan before the MCP router
    starts, and from the MCP server's own import for standalone runs."""
    conn = _connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS worlds (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                concept TEXT NOT NULL,
                starting_location_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ready',  -- 'ready' | 'claimed'
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                -- Scene shown at low opacity while in this world: SVG text
                -- (backdrop_mode='svg') or a data:image/png URI ('local').
                -- Name is a misnomer for raster mode; not worth a rename
                -- migration. NULL = no art.
                backdrop_svg TEXT,
                -- {summary, steps: [{anchor, requirement}]} — the journey to
                -- victory. NULL = pre-journey world (single-fact era).
                resolution_json TEXT
            );
            CREATE TABLE IF NOT EXISTS locations (
                id TEXT PRIMARY KEY,
                world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                description TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS exits (
                world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
                location_id TEXT NOT NULL,
                direction TEXT NOT NULL,
                to_location_id TEXT NOT NULL,
                PRIMARY KEY (location_id, direction)
            );
            CREATE TABLE IF NOT EXISTS npcs (
                id TEXT PRIMARY KEY,
                world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
                location_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL
            );
            -- Pre-authored secrets (weak spots, hidden doors, puzzle
            -- solutions) as key-value pairs against an entity — a stable
            -- schema no matter what fact types future modes add.
            CREATE TABLE IF NOT EXISTS world_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
                entity_id TEXT NOT NULL,   -- location/npc id, or the world id
                key TEXT NOT NULL,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS games (
                id TEXT PRIMARY KEY,
                world_id TEXT NOT NULL REFERENCES worlds(id),
                location_id TEXT NOT NULL,
                history_json TEXT NOT NULL DEFAULT '[]',
                last_response_json TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_active_at TEXT NOT NULL DEFAULT (datetime('now')),
                -- 'active' | 'won' | 'lost'. Won is model-triggered against
                -- the world's resolution steps (all must be complete — code
                -- enforced); lost is flipped in code when the last living
                -- player hits 0 HP.
                status TEXT NOT NULL DEFAULT 'active',
                -- Completed resolution-step indexes, e.g. '[0, 2]'.
                resolution_progress_json TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS game_players (
                id TEXT PRIMARY KEY,
                game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                token TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                joined_at TEXT NOT NULL DEFAULT (datetime('now')),
                -- Fixed pools (see PLAYER_MAX_HP/MANA); the model judges
                -- damage magnitude from the description, code owns the math.
                hp INTEGER NOT NULL DEFAULT 100,
                max_hp INTEGER NOT NULL DEFAULT 100,
                mana INTEGER NOT NULL DEFAULT 100,
                max_mana INTEGER NOT NULL DEFAULT 100
            );
            -- Fog-of-war: which rooms each game's party has stood in. Only
            -- these (plus stub exits) are ever sent to clients.
            CREATE TABLE IF NOT EXISTS game_visits (
                game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                location_id TEXT NOT NULL,
                PRIMARY KEY (game_id, location_id)
            );
            -- Server-global key/value settings (e.g. backdrop_mode) — they
            -- affect shared resources like the world pool, so they live
            -- here rather than in any browser.
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
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
        # Additive, idempotent migrations for DBs predating each feature.
        for ddl in (
            "ALTER TABLE worlds ADD COLUMN backdrop_svg TEXT",
            "ALTER TABLE worlds ADD COLUMN resolution_json TEXT",
            "ALTER TABLE games ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
            "ALTER TABLE games ADD COLUMN resolution_progress_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE game_players ADD COLUMN hp INTEGER NOT NULL DEFAULT 100",
            "ALTER TABLE game_players ADD COLUMN max_hp INTEGER NOT NULL DEFAULT 100",
            "ALTER TABLE game_players ADD COLUMN mana INTEGER NOT NULL DEFAULT 100",
            "ALTER TABLE game_players ADD COLUMN max_mana INTEGER NOT NULL DEFAULT 100",
        ):
            try:
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass  # column already exists
        conn.commit()
    finally:
        conn.close()


def sanitize_player_text(text: str) -> str:
    """Every player-authored string that reaches the model conversation goes
    through here. Square brackets are the server's channel there ([Name]:
    attribution, [System note: ...]) — swap them for parens so no message,
    name, or description can forge those lines. Newlines stay: multi-line
    roleplay is legitimate once brackets can't start a fake line."""
    return text.replace("[", "(").replace("]", ")").strip()


def _sanitize_name(name: str) -> str:
    # Names additionally flatten newlines and clamp — they're inlined into
    # single-line attribution prefixes.
    return sanitize_player_text(name.replace("\n", " ").replace("\r", " "))[:30]


def insert_world(world: dict, status: str = "ready") -> str:
    """Persist a validated generator payload as one world, prefixing every
    slug with the world id so entity ids are globally unique. Returns the
    world id. `world` shape: {title, concept, starting_location,
    locations: [{id, name, description, exits: [{direction, to}]}],
    npcs: [{id, location, name, description}],
    facts: [{entity: slug|'world', key, value}]}.
    """
    world_id = uuid.uuid4().hex[:8]
    qualify = lambda slug: f"{world_id}:{slug}"  # noqa: E731

    conn = _connect()
    try:
        resolution = world.get("resolution")
        resolution_json = None
        if resolution:
            resolution_json = json.dumps(
                {
                    "summary": resolution["summary"],
                    "steps": [
                        {"anchor": qualify(s["anchor"]), "requirement": s["requirement"]}
                        for s in resolution["steps"]
                    ],
                }
            )
        conn.execute(
            "INSERT INTO worlds (id, title, concept, starting_location_id, status, "
            "backdrop_svg, resolution_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                world_id,
                world["title"],
                world["concept"],
                qualify(world["starting_location"]),
                status,
                world.get("backdrop_svg"),
                resolution_json,
            ),
        )
        for loc in world["locations"]:
            conn.execute(
                "INSERT INTO locations (id, world_id, name, description) VALUES (?, ?, ?, ?)",
                (qualify(loc["id"]), world_id, loc["name"], loc["description"]),
            )
            for ex in loc["exits"]:
                conn.execute(
                    "INSERT INTO exits (world_id, location_id, direction, to_location_id) "
                    "VALUES (?, ?, ?, ?)",
                    (world_id, qualify(loc["id"]), ex["direction"], qualify(ex["to"])),
                )
        for npc in world["npcs"]:
            conn.execute(
                "INSERT INTO npcs (id, world_id, location_id, name, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (qualify(npc["id"]), world_id, qualify(npc["location"]), npc["name"], npc["description"]),
            )
        for fact in world.get("facts", []):
            entity = world_id if fact["entity"] == "world" else qualify(fact["entity"])
            conn.execute(
                "INSERT INTO world_facts (world_id, entity_id, key, value) VALUES (?, ?, ?, ?)",
                (world_id, entity, fact["key"], fact["value"]),
            )
        conn.commit()
        return world_id
    finally:
        conn.close()


def claim_world(world_id: str | None = None) -> dict | None:
    """Atomically take one ready world out of the pool for a new game —
    a specific one when world_id is given (None if it's gone or already
    claimed), else the oldest ready one (None = pool empty, caller then
    generates on demand)."""
    conn = _connect()
    try:
        row = conn.execute(
            "UPDATE worlds SET status = 'claimed' WHERE id = "
            "(SELECT id FROM worlds WHERE status = 'ready' AND (? IS NULL OR id = ?) "
            "ORDER BY created_at LIMIT 1) "
            "RETURNING id, title, concept, starting_location_id",
            (world_id, world_id),
        ).fetchone()
        conn.commit()
        return dict(row) if row else None
    finally:
        conn.close()


def list_ready_worlds() -> list[dict]:
    """The pool as shown to a player choosing a world for a new game."""
    conn = _connect()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, title, concept, backdrop_svg FROM worlds "
                "WHERE status = 'ready' ORDER BY created_at"
            )
        ]
    finally:
        conn.close()


def ready_world_count() -> int:
    conn = _connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM worlds WHERE status = 'ready'").fetchone()[0]
    finally:
        conn.close()


def get_world(world_id: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, title, concept, starting_location_id, status, backdrop_svg "
            "FROM worlds WHERE id = ?",
            (world_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


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
    # Descriptions reach the SYSTEM prompt (roster block) and join notices —
    # sanitize at insert so every downstream read is already safe.
    clean_description = sanitize_player_text(description)
    conn.execute(
        "INSERT INTO game_players (id, game_id, token, name, description) VALUES (?, ?, ?, ?, ?)",
        (player_id, game_id, token, sanitized, clean_description),
    )
    # The sanitized name goes back to the client — it's what every other
    # player will see, so the joiner's stored session must match it.
    return {
        "player_id": player_id,
        "player_token": token,
        "name": sanitized,
        "description": clean_description,
    }


def create_game(name: str, description: str, world: dict) -> dict:
    """New room in a claimed world + its first player, one transaction.
    `world` is the claim_world()/get_world() row. Returns
    {game_id, player_id, player_token, name}."""
    conn = _connect()
    try:
        game_id = _new_room_code(conn)
        conn.execute(
            "INSERT INTO games (id, world_id, location_id) VALUES (?, ?, ?)",
            (game_id, world["id"], world["starting_location_id"]),
        )
        # The threshold counts as visited — the map never starts empty.
        conn.execute(
            "INSERT INTO game_visits (game_id, location_id) VALUES (?, ?)",
            (game_id, world["starting_location_id"]),
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


def remove_player(game_id: str, token: str) -> dict | None:
    """Delete a player from a game. Returns {name, remaining} (remaining =
    players still in the room) or None if the token doesn't match."""
    conn = _connect()
    try:
        row = conn.execute(
            "DELETE FROM game_players WHERE game_id = ? AND token = ? RETURNING name",
            (game_id, token),
        ).fetchone()
        if row is None:
            return None
        remaining = conn.execute(
            "SELECT COUNT(*) FROM game_players WHERE game_id = ?", (game_id,)
        ).fetchone()[0]
        conn.commit()
        return {"name": row["name"], "remaining": remaining}
    finally:
        conn.close()


def delete_game(game_id: str) -> None:
    """Delete a game and its single-use world; cascades players, log rows,
    and all world entities. Same order as delete_idle_games: game first —
    games.world_id has no ON DELETE, so the world must outlive the row
    pointing at it."""
    conn = _connect()
    try:
        row = conn.execute("SELECT world_id FROM games WHERE id = ?", (game_id,)).fetchone()
        if row is not None:
            conn.execute("DELETE FROM games WHERE id = ?", (game_id,))
            conn.execute("DELETE FROM worlds WHERE id = ?", (row["world_id"],))
            conn.commit()
    finally:
        conn.close()


def get_game(game_id: str) -> dict | None:
    """Game row joined with its world's title/concept — every caller that
    loads a game also wants the world context for the prompt or the UI."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT g.id, g.world_id, g.location_id, g.last_response_json, g.last_active_at, "
            "g.status, w.title AS world_title, w.concept AS world_concept, "
            "w.backdrop_svg AS world_backdrop "
            "FROM games g JOIN worlds w ON w.id = g.world_id WHERE g.id = ?",
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
                "SELECT name, description, hp, max_hp, mana, max_mana "
                "FROM game_players WHERE game_id = ? ORDER BY rowid",
                (game_id,),
            )
        ]
    finally:
        conn.close()


def get_player_by_token(game_id: str, token: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, name, description, hp FROM game_players WHERE game_id = ? AND token = ?",
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
        entries = []
        for r in rows:
            entry = {
                "role": r["role"],
                "player_id": r["player_id"],
                "player_name": r["player_name"],
                "text": r["text"],
            }
            # Roll rows store their payload as JSON in text — surface it as
            # an object so the frontend renders the die, not the JSON.
            if r["role"] == "roll":
                entry["roll"] = json.loads(r["text"])
            entries.append(entry)
        return entries, (rows[-1]["id"] if rows else 0)
    finally:
        conn.close()


def get_visited_map(game_id: str) -> dict:
    """Fog-of-war map data: visited rooms (with names), direction-labeled
    edges between visited pairs, and stub exits toward unvisited rooms —
    whose names deliberately never leave the server. Unions the party's
    current location so pre-feature games start from where they stand."""
    conn = _connect()
    try:
        game = conn.execute(
            "SELECT location_id FROM games WHERE id = ?", (game_id,)
        ).fetchone()
        if game is None:
            return {"rooms": [], "edges": [], "stubs": []}
        visited = {
            r["location_id"]
            for r in conn.execute(
                "SELECT location_id FROM game_visits WHERE game_id = ?", (game_id,)
            )
        }
        visited.add(game["location_id"])

        placeholders = ",".join("?" * len(visited))
        # Descriptions are fair game for visited rooms — the party already
        # heard them narrated on arrival.
        rooms = [
            dict(r)
            for r in conn.execute(
                f"SELECT id, name, description FROM locations WHERE id IN ({placeholders})",
                tuple(visited),
            )
        ]
        edges, stubs = [], []
        for r in conn.execute(
            f"SELECT location_id, direction, to_location_id FROM exits "
            f"WHERE location_id IN ({placeholders})",
            tuple(visited),
        ):
            if r["to_location_id"] in visited:
                edges.append(
                    {"from": r["location_id"], "direction": r["direction"], "to": r["to_location_id"]}
                )
            else:
                stubs.append({"from": r["location_id"], "direction": r["direction"]})
        return {"rooms": rooms, "edges": edges, "stubs": stubs}
    finally:
        conn.close()


def get_milestones(game_id: str) -> dict:
    """{done, total} for the dots — step text stays server-side. 0/0 for
    games on pre-journey worlds."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT g.resolution_progress_json, w.resolution_json "
            "FROM games g JOIN worlds w ON w.id = g.world_id WHERE g.id = ?",
            (game_id,),
        ).fetchone()
        if row is None or row["resolution_json"] is None:
            return {"done": 0, "total": 0}
        total = len(json.loads(row["resolution_json"])["steps"])
        done = len(json.loads(row["resolution_progress_json"]))
        return {"done": done, "total": total}
    finally:
        conn.close()


def get_setting(key: str, default: str) -> str:
    conn = _connect()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def set_setting(key: str, value: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def delete_idle_games(days: int = 30) -> int:
    """Delete games idle past the cutoff; cascades players and log rows, and
    deletes each game's (single-use) world — which cascades its locations,
    exits, npcs, and facts. Returns how many games were deleted."""
    conn = _connect()
    try:
        world_ids = [
            r[0]
            for r in conn.execute(
                "SELECT world_id FROM games WHERE last_active_at < datetime('now', ?)",
                (f"-{days} days",),
            )
        ]
        cursor = conn.execute(
            "DELETE FROM games WHERE last_active_at < datetime('now', ?)", (f"-{days} days",)
        )
        deleted = cursor.rowcount
        for world_id in world_ids:
            conn.execute("DELETE FROM worlds WHERE id = ?", (world_id,))
        conn.commit()
        return deleted
    finally:
        conn.close()
