"""World generation eval — structure and tone of a real generated world.

Generates one world live (generate_world validates structure internally or
raises), then asserts the softer qualities the validator can't: counts near
the requested range, facts that are concrete, and an LLM-judged tone check
on the concept and a location description.

Requires ANTHROPIC_API_KEY; skipped otherwise. Slow and costs real tokens —
this is an eval, not a unit test; run deliberately, not on every `pytest`
invocation.
"""

import json
import os

import anthropic
import pytest

from app.worldgen import DEFAULT_LOCATIONS, DEFAULT_NPCS, generate_world

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"), reason="requires a live Anthropic API key"
)

JUDGE_SYSTEM = """\
You are grading world-building prose for a text adventure. The target
register is Darkest Dungeon: grimdark, punishing, atmospheric dread, gothic
horror. Cheerful, whimsical, or light-fantasy prose is a failure.

Score the passage 1-5:
5 = fully in register, evocative and specific
4 = in register with a minor lapse
3 = mixed, noticeable drift
2 = mostly out of register
1 = breaks the register entirely
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


async def _judge(client: anthropic.AsyncAnthropic, passage: str) -> tuple[int, str]:
    response = await client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1024,
        system=JUDGE_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
        messages=[{"role": "user", "content": passage}],
    )
    verdict = json.loads(next(b.text for b in response.content if b.type == "text"))
    return verdict["score"], verdict["reason"]


@pytest.mark.asyncio
async def test_generated_world_structure_and_tone():
    client = anthropic.AsyncAnthropic()
    world = await generate_world(client)  # raises if structurally invalid

    # Counts should land near the ask (validator bounds are looser on purpose).
    assert DEFAULT_LOCATIONS[0] - 1 <= len(world["locations"]) <= DEFAULT_LOCATIONS[1] + 1
    assert DEFAULT_NPCS[0] - 1 <= len(world["npcs"]) <= DEFAULT_NPCS[1] + 1
    # The prompt demands 4-8 secret facts; below that the world plays hollow.
    assert len(world["facts"]) >= 4
    # Facts must be adjudicable, not vibes — a one-word value can't be enforced.
    assert all(len(f["value"].split()) >= 5 for f in world["facts"]), world["facts"]

    score, reason = await _judge(
        client,
        f"World premise: {world['concept']}\n\n"
        f"A location: {world['locations'][0]['description']}",
    )
    assert score >= 4, f"tone drift in generated world {world['title']!r}: {reason}"
