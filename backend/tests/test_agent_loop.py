"""AgentLoop streaming internals, exercised against a faked Anthropic stream
and a faked MCP router — no API key, no subprocesses. Covers what the
endpoint tests (which fake the whole loop) can't: the paragraph break when
narration resumes after a tool round-trip, the turn_log cut around dice
rolls, the dice_pending/dice_result emissions, and that tool dispatch
actually applies the confused-deputy scope pin."""

import json
from types import SimpleNamespace

import pytest

from app.agent import AgentLoop


def _text_start():
    return SimpleNamespace(
        type="content_block_start", content_block=SimpleNamespace(type="text")
    )


def _delta(text):
    return SimpleNamespace(
        type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=text)
    )


def _tool_use(name, tool_input, tool_id):
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=tool_id)


def _final(stop_reason, content):
    return SimpleNamespace(stop_reason=stop_reason, content=content)


class _FakeStream:
    def __init__(self, events, final):
        self._events = events
        self._final = final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def gen():
            for event in self._events:
                yield event

        return gen()

    async def get_final_message(self):
        return self._final


class _FakeClient:
    """Pops one (events, final_message) round per messages.stream() call."""

    def __init__(self, rounds):
        self._rounds = list(rounds)
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        events, final = self._rounds.pop(0)
        return _FakeStream(events, final)


class _FakeRouter:
    def __init__(self):
        self.calls = []

    async def anthropic_tools(self):
        return []

    async def call(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        if name == "roll":
            payload = {"expression": "1d20", "rolls": [17], "modifier": 0, "total": 17}
            return {"text": json.dumps(payload), "is_error": False}
        if name == "get_party":
            return {
                "text": json.dumps({"game_id": "REAL1", "location_id": "w1:gate"}),
                "is_error": False,
            }
        if name == "get_location":
            return {
                "text": json.dumps({"name": "The Gate", "exits": {}, "npcs": []}),
                "is_error": False,
            }
        return {"text": "{}", "is_error": False}


SUGGEST = _tool_use(
    "suggest_actions", {"actions": [{"text": "Look around", "character": None}]}, "t_suggest"
)
WORLD = {"id": "w1", "title": "T", "concept": "C"}


def _agent(rounds, emitted, wait_for_roll=None):
    router = _FakeRouter()
    agent = AgentLoop(
        router,
        emit=lambda e: _collect(emitted, e),
        wait_for_roll=wait_for_roll,
    )
    agent.client = _FakeClient(rounds)
    return agent, router


async def _collect(sink, event):
    sink.append(event)


@pytest.mark.asyncio
async def test_roll_cuts_turn_log_and_breaks_paragraph():
    rounds = [
        # Round 1: narrate, then call roll.
        (
            [_text_start(), _delta("The blade hovers.")],
            _final(
                "tool_use",
                [
                    SimpleNamespace(type="text", text="The blade hovers."),
                    _tool_use("roll", {"expression": "1d20"}, "t_roll"),
                ],
            ),
        ),
        # Round 2: narration resumes (new text block), then suggest_actions.
        (
            [_text_start(), _delta("The die favors you.")],
            _final("tool_use", [SUGGEST]),
        ),
    ]
    emitted = []
    waited = []

    async def wait_for_roll(expression):
        waited.append(expression)

    agent, router = _agent(rounds, emitted, wait_for_roll)
    structured, _, turn_log = await agent.run_turn("REAL1", [], WORLD, [], "[Thorin]: I strike.")

    # Resumed narration gets a forced paragraph break, stored and streamed.
    assert structured.narrative == "The blade hovers.\n\nThe die favors you."
    assert {"type": "narrative_chunk", "text": "\n\n"} in emitted

    # turn_log is cut around the roll, in stream order.
    assert [e["role"] for e in turn_log] == ["narrator", "roll", "narrator"]
    assert turn_log[0]["text"] == "The blade hovers."
    assert json.loads(turn_log[1]["text"])["total"] == 17
    assert turn_log[2]["text"] == "The die favors you."

    # The turn blocked on the player's click, then broadcast the numbers.
    assert waited == ["1d20"]
    assert any(e["type"] == "dice_pending" for e in emitted)
    assert any(e["type"] == "dice_result" and e["total"] == 17 for e in emitted)


@pytest.mark.asyncio
async def test_dispatch_pins_game_id_and_refuses_foreign_entities():
    rounds = [
        (
            [],
            _final(
                "tool_use",
                [
                    # Model was talked into another room and another world.
                    _tool_use("get_party", {"game_id": "EVIL9"}, "t_party"),
                    _tool_use("get_location", {"location_id": "w2:throne"}, "t_loc"),
                ],
            ),
        ),
        ([], _final("tool_use", [SUGGEST])),
    ]
    emitted = []
    agent, router = _agent(rounds, emitted)
    await agent.run_turn("REAL1", [], WORLD, [], "[Thorin]: I look.")

    # get_party executed against the real game — twice: the pinned
    # model-driven call plus the post-turn direct read.
    assert router.calls.count(("get_party", {"game_id": "REAL1"})) == 2
    assert not any(args.get("game_id") == "EVIL9" for _, args in router.calls)
    # The foreign-world read never reached the router at all.
    assert not any(
        name == "get_location" and args.get("location_id") == "w2:throne"
        for name, args in router.calls
    )
