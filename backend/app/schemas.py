"""Structured output contract returned to the frontend on `turn_complete`.

Only `narrative` and `suggested_actions` are Claude's to emit (via streamed
text and the `suggest_actions` tool call, respectively). `location`,
`exits`, and `visible_npcs` are always filled from a fresh DB read after the
turn resolves — never trusted from the model — so narrated state can't drift
from persisted state. `world_updates` mirrors writes that already happened
through MCP tool calls; it is not an instruction the backend applies after
the fact.
"""

from pydantic import BaseModel, ConfigDict, Field


class WorldUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str


class StructuredResponse(BaseModel):
    narrative: str
    location: str
    exits: dict[str, str]
    visible_npcs: list[str]
    suggested_actions: list[str] = Field(min_length=1, max_length=4)
    world_updates: list[WorldUpdate] = Field(default_factory=list)
