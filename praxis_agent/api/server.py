"""FastAPI session/SSE API for the Praxis Lens agent.

- POST /sessions            {goal}     -> starts a background agent run, returns session_id
- POST /sessions/:id/message {text}    -> follow-up turn (resumes an interrupt if the agent
                                          is waiting on human input, otherwise a new turn)
- GET  /sessions/:id/events            -> SSE stream of live progress events
- GET  /sessions/:id                   -> current status
"""
from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from praxis_agent.agent.events import new_id, registry
from praxis_agent.agent.runner import send_message, sessions, start_session

app = FastAPI(title="Praxis Lens Agent")


class CreateSessionRequest(BaseModel):
    goal: str


class MessageRequest(BaseModel):
    text: str


@app.post("/sessions")
async def create_session(req: CreateSessionRequest):
    session_id = new_id("session")
    registry.get_or_create(session_id)
    asyncio.create_task(start_session(session_id, req.goal))
    return {"sessionId": session_id, "status": "running"}


@app.post("/sessions/{session_id}/message")
async def post_message(session_id: str, req: MessageRequest):
    info = sessions.get(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail="session not found")
    registry.get_or_create(session_id)
    asyncio.create_task(send_message(session_id, req.text))
    return {"sessionId": session_id, "status": "running"}


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    info = sessions.get(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"sessionId": session_id, "status": info.status, "goal": info.goal, "error": info.error}


@app.get("/sessions/{session_id}/events")
async def stream_events(session_id: str):
    bus = registry.get_or_create(session_id)
    queue = bus.subscribe()

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                yield {"event": event["type"], "data": json.dumps(event, default=str)}
        finally:
            bus.unsubscribe(queue)

    return EventSourceResponse(event_generator())


@app.get("/health")
async def health():
    return {"status": "ok"}
