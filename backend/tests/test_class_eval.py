"""Class-enforcement eval — abilities come from character descriptions.

LLM-as-judge: a two-character party (warrior + wizard) runs real turns where
a player attempts something their description doesn't support (the warrior
casting spells) or does support (the wizard casting spells), then a judge
call scores whether the GM granted or denied the ability correctly. This is
purely prompt-driven behavior, exactly the kind that regresses silently.

Requires ANTHROPIC_API_KEY; skipped otherwise. Slow and costs real tokens —
this is an eval, not a unit test; run deliberately, not on every `pytest`
invocation.
"""

import json
import os
from contextlib import asynccontextmanager

import anthropic
import pytest

from app import db
from app.agent import AgentLoop, MCPToolRouter
from app.worldgen import FALLBACK_WORLD

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"), reason="requires a live Anthropic API key"
)

# (acting player's message, whether their description supports it)
CASES = [
    ("[Thorin]: I cast a fireball at the darkness ahead.", False),
    ("[Thorin]: I conjure a magical shield around the party.", False),
    ("[Zara]: I conjure a small flame to light the passage.", True),
]

JUDGE_SYSTEM = """\
You are grading narration from a group text adventure's game master. The
party is:
- Thorin: a dwarf warrior with a battleaxe. No magical ability whatsoever.
- Zara: an elven wizard specializing in fire magic. No martial prowess.

You will be shown a player's attempted action and the GM's narration of the
outcome. Decide whether the GM GRANTED the ability (the attempt succeeds as
described, the character wields a power) or DENIED it (the attempt fails,
fizzles, is refused by the world, or is redirected — in-world failure counts
as denied even if narrated at length).
"""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "granted": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["granted", "reason"],
    "additionalProperties": False,
}


@asynccontextmanager
async def _fresh_router(db_path):
    # Started, used, and closed within one test function's task — MCP's
    # stdio_client uses an anyio task group whose enter/exit must happen in
    # the same asyncio Task, which a pytest-asyncio fixture spanning
    # separate setup/teardown callbacks doesn't guarantee.
    os.environ["WORLD_DB_PATH"] = str(db_path)
    db.init_db()
    r = MCPToolRouter()
    await r.start()
    try:
        yield r
    finally:
        await r.aclose()


async def _judge(client: anthropic.AsyncAnthropic, action: str, narrative: str) -> tuple[bool, str]:
    response = await client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1024,
        system=JUDGE_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": f"Attempted action:\n{action}\n\nGM narration:\n{narrative}",
            }
        ],
    )
    text = next(b.text for b in response.content if b.type == "text")
    verdict = json.loads(text)
    return verdict["granted"], verdict["reason"]


@pytest.mark.asyncio
@pytest.mark.parametrize("action,should_grant", CASES)
async def test_class_enforcement(tmp_path, action, should_grant):
    async def emit(event: dict) -> None:
        pass

    async with _fresh_router(tmp_path / "eval_world.db") as router:
        world_id = db.insert_world(FALLBACK_WORLD, status="claimed")
        world = db.get_world(world_id)
        game = db.create_game(
            "Thorin", "a dwarf warrior with a battleaxe. No magical ability.", world
        )
        db.add_player(
            game["game_id"], "Zara", "an elven wizard specializing in fire magic. No martial prowess."
        )
        roster = db.list_players(game["game_id"])
        agent = AgentLoop(router, emit)
        structured, _, _ = await agent.run_turn(
            game["game_id"],
            roster,
            {"title": FALLBACK_WORLD["title"], "concept": FALLBACK_WORLD["concept"]},
            [],
            action,
        )

    client = anthropic.AsyncAnthropic()
    granted, reason = await _judge(client, action, structured.narrative)

    assert granted == should_grant, (
        f"class enforcement failed on {action!r}: granted={granted} "
        f"(expected {should_grant}) reason={reason}"
    )
