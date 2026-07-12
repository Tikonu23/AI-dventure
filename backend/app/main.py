"""FastAPI app: multiplayer rooms. A game is a room code; every connected
browser subscribes to one GET SSE stream per room that carries all turn
events (narrative_chunk, tool_call, turn_complete, ...) for actor and
spectators alike — POST /turn itself returns plain JSON and exists for
submission + rejection (409 when a turn is already in flight).

Conversation history and the display log live in SQLite (app.db), so games
survive restarts. What does NOT survive restarts — and assumes a single
process (`fastapi dev`, no --workers) — are `subscribers`, `active_turns`,
and `pending_join_notices` below; running multiple workers would break turn
serialization and event fan-out.
"""

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app import db, worldgen
from app.agent import AgentLoop, MCPToolRouter

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CLEANUP_INTERVAL_SECONDS = 3600
IDLE_GAME_DAYS = 30
# How many generated worlds to keep ready — players pick from this menu
# when starting a new game, so it's also the size of that choice.
WORLD_POOL_SIZE = int(os.environ.get("WORLD_POOL_SIZE", "3"))

router = MCPToolRouter()

# Per-room fan-out: every connected browser gets its own queue. Turn events
# are broadcast to all of them, so spectators watch turns stream live.
subscribers: dict[str, set[asyncio.Queue]] = {}
# game_id -> acting player's name. Test-and-set with no `await` between check
# and set (atomic in a single event loop) — deliberately NOT an asyncio.Lock,
# which would queue the second submitter instead of rejecting them.
active_turns: dict[str, str] = {}
# Joins that landed while a turn was streaming — save_turn overwrites the
# whole history blob at turn end, so writing the join notice into the DB
# mid-turn would be lost. Drained into history at the next turn's start.
pending_join_notices: dict[str, list[str]] = {}
# game_id -> (release event, dice expression). The model turn blocks on the
# event until a player clicks the die; the expression rides along so /state
# can rehydrate the prompt for a reconnecting client.
pending_rolls: dict[str, tuple[asyncio.Event, str]] = {}
# Auto-roll backstop: a turn holds the room's turn lock, so an AFK player
# must not be able to deadlock the whole party.
ROLL_WAIT_SECONDS = 60


async def broadcast(game_id: str, event: dict) -> None:
    for queue in subscribers.get(game_id, set()):
        await queue.put(event)


async def cleanup_loop() -> None:
    while True:
        try:
            deleted = db.delete_idle_games(IDLE_GAME_DAYS)
            if deleted:
                logger.info("cleanup: deleted %d games idle > %d days", deleted, IDLE_GAME_DAYS)
        except Exception:
            logger.exception("cleanup tick failed")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


# Poked whenever a world is claimed so the pool refills immediately instead
# of waiting for the safety-net tick.
pool_wake = asyncio.Event()


async def world_pool_loop() -> None:
    while True:
        try:
            while db.ready_world_count() < WORLD_POOL_SIZE:
                logger.info("world pool below target %d — generating", WORLD_POOL_SIZE)
                world = await worldgen.generate_world(anthropic.AsyncAnthropic())
                world_id = db.insert_world(world)
                logger.info("world %s ready: %s", world_id, world["title"])
        except Exception:
            # API outage or repeated validation failure — back off rather
            # than hammering; on-demand generation still covers creates.
            logger.exception("world pool refill failed; retrying in 60s")
            await asyncio.sleep(60)
            continue
        pool_wake.clear()
        try:
            await asyncio.wait_for(pool_wake.wait(), timeout=600)
        except TimeoutError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # All tables must exist before the MCP server takes get_party calls.
    db.init_db()
    await router.start()
    background = [asyncio.create_task(cleanup_loop()), asyncio.create_task(world_pool_loop())]
    yield
    for task in background:
        task.cancel()
    await router.aclose()


app = FastAPI(lifespan=lifespan)


class JoinRequest(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    description: str = Field(min_length=1, max_length=500)
    # Chosen world from GET /worlds — create only; /join ignores it.
    world_id: str | None = None


class TurnRequest(BaseModel):
    token: str
    message: str
    # Whether the frontend is showing a player-bubble for this message (it
    # skips one for the auto-sent "Begin the adventure." opening) — the
    # stored log must mirror that exactly, so it's the caller's call to make.
    log_player_action: bool


def _require_player(game_id: str, token: str) -> dict:
    if db.get_game(game_id) is None:
        raise HTTPException(404, "unknown game")
    player = db.get_player_by_token(game_id, token)
    if player is None:
        raise HTTPException(403, "invalid player token")
    return player


@app.get("/worlds")
async def list_worlds() -> list[dict]:
    """Ready pool worlds for the new-game menu: [{id, title, concept}]."""
    return db.list_ready_worlds()


@app.post("/games")
async def create_game(req: JoinRequest) -> dict:
    if req.world_id:
        world = db.claim_world(req.world_id)
        if world is None:
            # Claimed between menu render and click (or never real) — an
            # honest 409 so the client refreshes the menu, rather than
            # silently starting a world the player didn't pick.
            raise HTTPException(409, {"code": "world_taken"})
        pool_wake.set()
        return db.create_game(req.name, req.description, world)

    world = db.claim_world()
    if world is None:
        # Pool empty (burst of creates, or generation has been failing) —
        # generate on demand while the frontend shows its loading state.
        # If generation itself fails, degrade to the hand-authored fallback
        # world rather than refusing the game.
        try:
            payload = await worldgen.generate_world(anthropic.AsyncAnthropic())
        except Exception:
            logger.exception("on-demand world generation failed — using fallback world")
            payload = worldgen.FALLBACK_WORLD
        world_id = db.insert_world(payload, status="claimed")
        world = db.get_world(world_id)
    pool_wake.set()
    return db.create_game(req.name, req.description, world)


@app.post("/games/{game_id}/join")
async def join_game(game_id: str, req: JoinRequest) -> dict:
    game_id = game_id.upper()
    if db.get_game(game_id) is None:
        raise HTTPException(404, "unknown game")
    player = db.add_player(game_id, req.name, req.description)
    name = player["name"]  # sanitized form

    notice = f"[System note: {name} joins the party — {req.description.strip()}]"
    if game_id in active_turns:
        pending_join_notices.setdefault(game_id, []).append(notice)
    else:
        db.append_history_user_message(game_id, notice)
    db.append_log(game_id, "system", f"{name} joins the party.")
    await broadcast(game_id, {"type": "player_joined", "name": name})
    return player


@app.get("/games/{game_id}/state")
async def game_state(game_id: str, token: str) -> dict:
    game_id = game_id.upper()
    _require_player(game_id, token)
    game = db.get_game(game_id)
    log_entries, last_log_id = db.load_log(game_id)

    if game["last_response_json"]:
        last = json.loads(game["last_response_json"])
        world = {
            "location": last["location"],
            "exits": last["exits"],
            "visible_npcs": last["visible_npcs"],
            "suggested_actions": last["suggested_actions"],
        }
    else:
        # No turn has resolved yet (fresh game, or a joiner arriving while
        # the opening turn streams) — read the world directly so the header
        # isn't blank.
        location = json.loads(
            (
                await router.call(
                    "get_location",
                    {
                        "location_id": json.loads(
                            (await router.call("get_party", {"game_id": game_id}))["text"]
                        )["location_id"]
                    },
                )
            )["text"]
        )
        world = {
            "location": location["name"],
            "exits": location["exits"],
            "visible_npcs": [n["name"] for n in location["npcs"]],
            "suggested_actions": [],
        }

    return {
        "game_id": game_id,
        "world_title": game["world_title"],
        "players": db.list_players(game_id),
        "log": log_entries,
        "last_log_id": last_log_id,
        **world,
        "turn_in_progress": game_id in active_turns,
        "actor": active_turns.get(game_id),
        "pending_roll": pending_rolls[game_id][1] if game_id in pending_rolls else None,
    }


class TokenRequest(BaseModel):
    token: str


@app.post("/games/{game_id}/roll")
async def resolve_roll(game_id: str, req: TokenRequest) -> dict:
    """Release a turn blocked on a pending dice roll."""
    game_id = game_id.upper()
    _require_player(game_id, req.token)
    # ponytail: any party member's click releases the die, not just the
    # actor's — the UI only offers the button to the actor; gate by player
    # id here if that ever needs enforcing.
    pending = pending_rolls.get(game_id)
    if pending is None:
        raise HTTPException(409, "no roll pending")
    pending[0].set()
    return {"ok": True}


@app.post("/games/{game_id}/leave")
async def leave_game(game_id: str, req: TokenRequest) -> dict:
    game_id = game_id.upper()
    player = _require_player(game_id, req.token)
    result = db.remove_player(game_id, req.token)
    name = player["name"]

    # Last one out — the room and its single-use world die now rather than
    # lingering until the 30-day idle cleanup.
    if result["remaining"] == 0:
        db.delete_game(game_id)
        return {"ok": True}

    # Mirror the join flow: the model hears about it via a history notice
    # (deferred if a turn is streaming — save_turn would clobber it),
    # everyone else via a log row + broadcast.
    notice = f"[System note: {name} leaves the party]"
    if game_id in active_turns:
        pending_join_notices.setdefault(game_id, []).append(notice)
    else:
        db.append_history_user_message(game_id, notice)
    db.append_log(game_id, "system", f"{name} leaves the party.")
    await broadcast(game_id, {"type": "player_left", "name": name})
    return {"ok": True}


@app.get("/games/{game_id}/events")
async def game_events(game_id: str) -> EventSourceResponse:
    # No token check: the room code is the capability — anyone who has it
    # could join outright anyway.
    game_id = game_id.upper()
    if db.get_game(game_id) is None:
        raise HTTPException(404, "unknown game")

    queue: asyncio.Queue = asyncio.Queue()

    async def generator() -> AsyncIterator[dict]:
        subscribers.setdefault(game_id, set()).add(queue)
        try:
            while True:
                event = await queue.get()
                yield {"data": json.dumps(event)}
        finally:
            subs = subscribers.get(game_id)
            if subs is not None:
                subs.discard(queue)
                if not subs:
                    del subscribers[game_id]

    return EventSourceResponse(generator())


@app.post("/games/{game_id}/turn")
async def turn(game_id: str, req: TurnRequest) -> dict:
    game_id = game_id.upper()
    player = _require_player(game_id, req.token)

    # First-come-wins: reject, don't queue. No await between the check and
    # the set, so two near-simultaneous submitters can't both pass.
    if game_id in active_turns:
        raise HTTPException(
            409, {"code": "turn_in_progress", "actor": active_turns[game_id]}
        )
    active_turns[game_id] = player["name"]

    try:
        # The message rides along so spectators can render the actor's bubble
        # live — otherwise other players' dialog only appears after a reload.
        await broadcast(
            game_id,
            {
                "type": "turn_started",
                "actor": player["name"],
                "actor_id": player["id"],
                "message": req.message,
                "logged": req.log_player_action,
            },
        )

        history = db.load_history(game_id)
        # Joins that arrived during the previous turn's stream — inject them
        # before this turn's action so the narration can acknowledge them.
        for notice in pending_join_notices.pop(game_id, []):
            history.append({"role": "user", "content": notice})

        # The opening "Begin the adventure." is a stage direction, not a
        # character's utterance — no attribution prefix.
        if req.log_player_action:
            action = f"[{player['name']}]: {req.message}"
        else:
            action = req.message

        game = db.get_game(game_id)
        world = {"title": game["world_title"], "concept": game["world_concept"]}
        roster = db.list_players(game_id)
        async def wait_for_roll(expression: str) -> None:
            release = asyncio.Event()
            pending_rolls[game_id] = (release, expression)
            try:
                await asyncio.wait_for(release.wait(), timeout=ROLL_WAIT_SECONDS)
            except TimeoutError:
                # Nobody clicked — roll anyway rather than hold the room.
                pass
            finally:
                pending_rolls.pop(game_id, None)

        agent = AgentLoop(
            router, emit=lambda event: broadcast(game_id, event), wait_for_roll=wait_for_roll
        )
        structured, new_history = await agent.run_turn(game_id, roster, world, history, action)

        log_entries = []
        if req.log_player_action:
            log_entries.append(
                {
                    "role": "player",
                    "player_id": player["id"],
                    "player_name": player["name"],
                    "text": req.message,
                }
            )
        log_entries.append({"role": "narrator", "text": structured.narrative})
        structured_json = structured.model_dump_json()
        log_id = db.save_turn(game_id, new_history, structured_json, log_entries)

        await broadcast(
            game_id,
            {
                "type": "turn_complete",
                "response": structured.model_dump(),
                "actor": player["name"],
                "log_id": log_id,
            },
        )
        return {"response": structured.model_dump()}
    except HTTPException:
        raise
    except Exception:
        logger.exception("turn failed for game %s", game_id)
        # Spectators are watching a turn that will never complete — tell them
        # so their input re-enables.
        await broadcast(game_id, {"type": "turn_error"})
        raise HTTPException(500, "turn failed")
    finally:
        active_turns.pop(game_id, None)
