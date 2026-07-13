"""Tone consistency eval — Darkest Dungeon mode.

LLM-as-judge: 5 fixed player inputs (including adversarial ones that invite
an out-of-register reply — a joke, a cheerful song) each run through a real
turn, then a judge call scores whether the narration held a grimdark
gothic-horror register. Requires ANTHROPIC_API_KEY; skipped otherwise.

Slow and costs real tokens (generation + judging per input) — this is an
eval, not a unit test; run deliberately, not on every `pytest` invocation.
"""

import json
import os
from contextlib import asynccontextmanager

import anthropic
import pytest

from app.agent import AgentLoop, MCPToolRouter

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"), reason="requires a live Anthropic API key"
)

FIXED_INPUTS = [
    "I look around.",
    "I greet Brother Aldric.",
    "Tell me a joke.",
    "I open my inventory to check my gold.",
    "I sing a cheerful tavern song to lighten the mood.",
]

JUDGE_SYSTEM = """\
You are grading narration from a text adventure's game master for tone \
consistency. The target register is Darkest Dungeon: grimdark, punishing, \
atmospheric dread, gothic horror. Cheerful, whimsical, or light-fantasy \
prose is a failure even if the content is otherwise coherent — including \
when the failure was invited by the player's own request (a joke, a song).

Score the passage 1-5:
5 = fully in register, no lapses
4 = in register with a minor lapse
3 = mixed, noticeable drift from the register
2 = mostly out of register
1 = comedic, cheerful, or otherwise breaks immersion entirely
"""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "reason": {"type": "string"},
    },
    "required": ["score", "reason"],
    "additionalProperties": False,
}


@asynccontextmanager
async def _fresh_router(db_path):
    # Started, used, and closed within one test function's task — MCP's
    # stdio_client uses an anyio task group whose enter/exit must happen in
    # the same asyncio Task, which a pytest-asyncio fixture spanning
    # separate setup/teardown callbacks doesn't guarantee.
    os.environ["WORLD_DB_PATH"] = str(db_path)
    r = MCPToolRouter()
    await r.start()
    try:
        yield r
    finally:
        await r.aclose()


async def _judge(client: anthropic.AsyncAnthropic, narrative: str) -> tuple[int, str]:
    response = await client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1024,
        system=JUDGE_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
        messages=[{"role": "user", "content": narrative}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    verdict = json.loads(text)
    return verdict["score"], verdict["reason"]


@pytest.mark.asyncio
@pytest.mark.parametrize("player_action", FIXED_INPUTS)
async def test_tone_consistency(tmp_path, player_action):
    async def emit(event: dict) -> None:
        pass

    async with _fresh_router(tmp_path / "eval_world.db") as router:
        agent = AgentLoop(router, emit)
        # "p1" is the only player row the fresh eval DB seeds.
        structured, _, _ = await agent.run_turn("p1", [], player_action)

    client = anthropic.AsyncAnthropic()
    score, reason = await _judge(client, structured.narrative)

    assert score >= 4, f"tone drift on {player_action!r}: score={score} reason={reason}"
