"""Structured output contract returned to the frontend on `turn_complete`.

Only `narrative` and `suggested_actions` are Claude's to emit (via streamed
text and the `suggest_actions` tool call, respectively). `location`,
`exits`, and `visible_npcs` are always filled from a fresh DB read after the
turn resolves — never trusted from the model — so narrated state can't drift
from persisted state. `world_updates` mirrors writes that already happened
through MCP tool calls; it is not an instruction the backend applies after
the fact.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SuggestedAction(BaseModel):
    text: str
    # Player character this suggestion is for; None = anyone can take it.
    # The frontend hides suggestions targeted at other characters.
    character: str | None = None

    # Bare strings (pre-targeting turns in old games, code-side fallbacks)
    # coerce to for-anyone rather than forcing a data migration.
    @model_validator(mode="before")
    @classmethod
    def _coerce_bare_string(cls, value):
        return {"text": value} if isinstance(value, str) else value


class WorldUpdate(BaseModel):
    # Each update `type` carries different fields (location_change has
    # player/to; a future item_pickup would carry different ones) — extra
    # fields are allowed rather than modeling every type as its own class.
    model_config = ConfigDict(extra="allow")

    type: str


class StructuredResponse(BaseModel):
    narrative: str
    location: str
    exits: dict[str, str]
    visible_npcs: list[str]
    suggested_actions: list[SuggestedAction] = Field(min_length=1, max_length=4)
    world_updates: list[WorldUpdate] = Field(default_factory=list)
