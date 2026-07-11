"""The turn loop: streams narrative text, executes real MCP tool calls
(which is what produces the Agent Activity Panel's tool_call events and is
what actually persists world state), and returns the structured envelope.

Data-flow shape (decided up front so streaming and structured output don't
fight each other — see project plan's "Structured Output Contract"):
  - `narrative` is streamed assistant text.
  - World mutations happen via real MCP tool calls during the turn; those
    calls ARE the tool_call events and ARE what writes to SQLite.
    `world_updates` in the response mirrors writes that already happened,
    it is not an instruction applied afterward.
  - `location` / `exits` / `visible_npcs` are filled from a fresh DB read
    after the turn — retrieved, never re-derived from the narrative.
  - Only `narrative` and `suggested_actions` (via the `suggest_actions`
    tool call) are genuinely Claude's to emit.

Retry/degrade: schema-violation retry only applies to the "can't even
construct a valid response" case. `suggest_actions` uses `strict: true`,
so its input is schema-guaranteed by the API — no retry needed there.
Retrying the whole model turn on failure is unsafe once any MCP write
tool has already run (it would double-apply the mutation), so a mid-loop
failure degrades using whatever narrative was captured plus a fresh DB
read, rather than re-running the turn.
"""

import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path

import anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.schemas import StructuredResponse

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parent.parent
MODEL = "claude-opus-4-8"
# ponytail: flat cap, not per-scenario tuning — raise if a legitimate turn
# needs more than 8 tool-call round-trips before calling suggest_actions.
MAX_CONTINUATIONS = 8

SYSTEM_PROMPT_TEMPLATE = """\
You are the game master for a Darkest Dungeon-style text adventure: \
grimdark, punishing, atmospheric dread. High stakes, morally ambiguous. \
Gothic horror register — never cheerful, never cute.

The campaign's world — ground every scene in this premise:
{world_title}: {world_concept}

Locations and NPCs carry pre-authored secret `facts` in their tool results. \
These are the world's hidden truth: enforce them exactly (a hidden door \
opens the way the fact says, a weakness works only as written), foreshadow \
them, and let players earn their discovery through searching, experimenting, \
and questioning — never state them unprompted, and never contradict or \
re-invent them.

This is a group adventure. The party (they always travel and act as a \
single unit — one location, one scene, one narrative thread):
{roster}

Each player message is prefixed "[Name]:" identifying who acts. Judge every \
action against that character's description — a warrior cannot cast a \
wizard's spells, a wizard cannot match a warrior's brute force. Each \
character brings only what their description supports. Narrate \
out-of-character attempts as in-world failures or fumbles; never silently \
grant abilities the description doesn't justify. Never take actions on \
behalf of a character whose player didn't speak this turn, beyond their \
presence in the scene.

The current game's ID is "{game_id}". Pass this exact value as the \
game_id argument to any tool that takes one — never guess or invent one. \
Movement uses `move_party` and moves the entire party together.

World state (locations, exits, NPCs, dice rolls) is retrieved through your \
tools. Never invent a room, an NPC, or a dice result that a tool didn't \
give you. If a player tries something that violates the physical world \
(flying, walking through walls), redirect them narratively without \
breaking immersion. If a player tries something merely unwise but \
physically possible, allow it and narrate the consequences.

Every turn, after narrating, call `suggest_actions` exactly once with 2-4 \
short suggested next actions.
"""

SUGGEST_ACTIONS_TOOL = {
    "name": "suggest_actions",
    "description": (
        "Call this once, after narrating, with 2-4 short suggested next "
        "actions for the player."
    ),
    "input_schema": {
        # strict-mode array schemas don't support minItems/maxItems other
        # than 0 or 1 — the 2-4 count is enforced by prompt + a code-side
        # clamp instead (see suggested_actions handling below).
        "type": "object",
        "properties": {
            "actions": {
                "type": "array",
                "items": {"type": "string"},
            }
        },
        "required": ["actions"],
        "additionalProperties": False,
    },
    "strict": True,
}


class MCPToolRouter:
    """Owns the MCP client sessions and dispatches tool_use calls to them."""

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self.sessions: dict[str, ClientSession] = {}
        self.tool_owner: dict[str, str] = {}

    async def start(self) -> None:
        # stdio_client only inherits a fixed safe-list of env vars by
        # default (PATH, HOME, ...) — WORLD_DB_PATH must be forwarded
        # explicitly or the eval/test harness's isolated DB override is
        # silently ignored by the spawned server subprocess.
        env = {"WORLD_DB_PATH": os.environ["WORLD_DB_PATH"]} if "WORLD_DB_PATH" in os.environ else None
        for server_name, module in (
            ("sqlite", "app.mcp_servers.sqlite_server"),
            ("dice", "app.mcp_servers.dice_server"),
        ):
            params = StdioServerParameters(
                command=sys.executable, args=["-m", module], cwd=str(BACKEND_ROOT), env=env
            )
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.sessions[server_name] = session
            result = await session.list_tools()
            for t in result.tools:
                self.tool_owner[t.name] = server_name

    async def anthropic_tools(self) -> list[dict]:
        tools = [SUGGEST_ACTIONS_TOOL]
        for server_name, session in self.sessions.items():
            result = await session.list_tools()
            for t in result.tools:
                tools.append(
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "input_schema": t.inputSchema,
                    }
                )
        return tools

    async def call(self, name: str, arguments: dict) -> dict:
        """Call an MCP tool directly (not model-driven) — used for the
        post-turn DB read that fills location/exits/visible_npcs."""
        server_name = self.tool_owner[name]
        result = await self.sessions[server_name].call_tool(name, arguments)
        text_parts = [c.text for c in result.content if c.type == "text"]
        return {"text": "\n".join(text_parts) or "{}", "is_error": bool(result.isError)}

    async def aclose(self) -> None:
        await self._stack.aclose()


class AgentLoop:
    def __init__(self, router: MCPToolRouter, emit: Callable[[dict], Awaitable[None]]) -> None:
        self.router = router
        self.emit = emit
        self.client = anthropic.AsyncAnthropic()

    async def run_turn(
        self,
        game_id: str,
        roster: list[dict],
        world: dict,
        history: list[dict],
        player_action: str,
    ) -> tuple[StructuredResponse, list[dict]]:
        """roster is [{name, description}, ...] — rebuilt from the DB each
        turn so mid-game joins are always reflected in the system prompt.
        world is {title, concept} — this game's generated premise."""
        try:
            return await self._run_turn_inner(game_id, roster, world, history, player_action)
        except Exception:
            logger.exception("turn failed for game %s", game_id)
            location = await self._read_location(game_id)
            fallback = StructuredResponse(
                narrative=(
                    "The telling falters — something in the dark swallows "
                    "the thread of the story. Try your action again."
                ),
                location=location["name"],
                exits=location["exits"],
                visible_npcs=[n["name"] for n in location["npcs"]],
                suggested_actions=["Try again", "Look around"],
                world_updates=[],
            )
            return fallback, history

    async def _read_location(self, game_id: str) -> dict:
        party = json.loads((await self.router.call("get_party", {"game_id": game_id}))["text"])
        return json.loads(
            (await self.router.call("get_location", {"location_id": party["location_id"]}))["text"]
        )

    async def _run_turn_inner(
        self,
        game_id: str,
        roster: list[dict],
        world: dict,
        history: list[dict],
        player_action: str,
    ) -> tuple[StructuredResponse, list[dict]]:
        tools = await self.router.anthropic_tools()
        roster_block = "\n".join(f"- {p['name']}: {p['description']}" for p in roster)
        messages = [*history, {"role": "user", "content": player_action}]
        world_updates: list[dict] = []
        suggested_actions = ["Look around"]
        got_suggest_actions = False
        narrative_parts: list[str] = []

        # for/else: the `else` only runs if the loop exhausts MAX_CONTINUATIONS
        # without hitting a `break` below (i.e. neither max_tokens, end_turn,
        # nor suggest_actions ended it) — that's the runaway-loop case.
        for iteration in range(MAX_CONTINUATIONS):
            async with self.client.messages.stream(
                model=MODEL,
                max_tokens=16000,
                system=SYSTEM_PROMPT_TEMPLATE.format(
                    game_id=game_id,
                    roster=roster_block,
                    world_title=world["title"],
                    world_concept=world["concept"],
                ),
                thinking={"type": "adaptive"},
                tools=tools,
                messages=messages,
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        narrative_parts.append(event.delta.text)
                        await self.emit({"type": "narrative_chunk", "text": event.delta.text})
                response = await stream.get_final_message()

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "max_tokens":
                logger.warning(
                    "turn for game %s hit max_tokens on iteration %d — narrative may be "
                    "truncated and suggest_actions may not have run",
                    game_id,
                    iteration,
                )
                break

            if response.stop_reason != "tool_use":
                break

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                if block.name == "suggest_actions":
                    actions = block.input.get("actions") or []
                    if actions:
                        suggested_actions = actions[:4]
                    got_suggest_actions = True
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": "ok"}
                    )
                    continue

                await self.emit({"type": "tool_call", "tool": block.name, "status": "running"})
                try:
                    result = await self.router.call(block.name, block.input)
                    # ponytail: move_party is the only write tool so far, so
                    # it's the only source of world_updates. Add a case per new
                    # write tool (e.g. give_item, start_quest) as they show up.
                    if block.name == "move_party" and not result["is_error"]:
                        moved = json.loads(result["text"])
                        if "to" in moved:
                            world_updates.append({"type": "location_change", "to": moved["to"]})
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result["text"],
                            "is_error": result["is_error"],
                        }
                    )
                finally:
                    await self.emit({"type": "tool_call", "tool": block.name, "status": "done"})

            messages.append({"role": "user", "content": tool_results})

            # suggest_actions is the model's signal that it's done narrating —
            # tool_results for this batch are already appended above so history
            # stays valid, but there's nothing left to continue the loop for.
            if got_suggest_actions:
                break
        else:
            logger.warning(
                "turn for game %s hit the %d-continuation cap without reaching end_turn",
                game_id,
                MAX_CONTINUATIONS,
            )

        if not got_suggest_actions:
            logger.warning(
                "turn for game %s ended without a suggest_actions call — falling back to %r",
                game_id,
                suggested_actions,
            )
        if not "".join(narrative_parts).strip():
            logger.warning("turn for game %s produced no narrative text", game_id)

        location = await self._read_location(game_id)

        structured = StructuredResponse(
            narrative="".join(narrative_parts).strip(),
            location=location["name"],
            exits=location["exits"],
            visible_npcs=[n["name"] for n in location["npcs"]],
            suggested_actions=suggested_actions,
            world_updates=world_updates,
        )
        return structured, messages
