"""FastAPI app: one POST /turn endpoint streaming the three SSE event
types from the project plan (tool_call, narrative_chunk, turn_complete)
for a single player action.

Conversation history is kept in memory per player_id — it does not survive
a server restart. World state (location, NPCs) does, via SQLite, which is
what Phase 1's save/reload requirement is actually about.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.agent import AgentLoop, MCPToolRouter

load_dotenv()
logging.basicConfig(level=logging.INFO)

router = MCPToolRouter()
histories: dict[str, list] = {}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await router.start()
    yield
    await router.aclose()


app = FastAPI(lifespan=lifespan)


class TurnRequest(BaseModel):
    player_id: str
    message: str


@app.post("/turn")
async def turn(req: TurnRequest) -> EventSourceResponse:
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: dict) -> None:
        await queue.put(event)

    async def run() -> None:
        agent = AgentLoop(router, emit)
        history = histories.get(req.player_id, [])
        structured, new_history = await agent.run_turn(req.player_id, history, req.message)
        histories[req.player_id] = new_history
        await queue.put({"type": "turn_complete", "response": structured.model_dump()})
        await queue.put(None)  # sentinel: no more events

    async def generator() -> AsyncIterator[dict]:
        task = asyncio.create_task(run())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield {"data": json.dumps(event)}
        finally:
            await task

    return EventSourceResponse(generator())
