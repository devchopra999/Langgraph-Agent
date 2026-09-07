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
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from praxis_agent.agent.events import new_id, registry
from praxis_agent.agent.runner import send_message, sessions, start_session, stop_session

PUBLIC_DIR = Path(__file__).resolve().parent.parent.parent / "public"

app = FastAPI(title="Praxis Lens Agent")


class CreateSessionRequest(BaseModel):
    goal: str


class MessageRequest(BaseModel):
    text: str


@app.post("/sessions")
async def create_session(req: CreateSessionRequest):
    session_id = new_id("session")
    registry.get_or_create(session_id)
    sessions.create(session_id, req.goal)
    task = asyncio.create_task(start_session(session_id, req.goal))
    sessions.set_task(session_id, task)
    return {"sessionId": session_id, "status": "running"}


@app.post("/sessions/{session_id}/message")
async def post_message(session_id: str, req: MessageRequest):
    info = sessions.get(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail="session not found")
    registry.get_or_create(session_id)
    task = asyncio.create_task(send_message(session_id, req.text))
    sessions.set_task(session_id, task)
    return {"sessionId": session_id, "status": "running"}


@app.post("/sessions/{session_id}/stop")
async def post_stop_session(session_id: str):
    info = stop_session(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"sessionId": session_id, "status": info.status}


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    info = sessions.get(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"sessionId": session_id, "status": info.status, "goal": info.goal, "error": info.error}


@app.get("/sessions/{session_id}/report")
async def get_session_report(session_id: str, format: Literal["markdown", "json"] = "markdown"):
    info = sessions.get(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail="session not found")
    if info.report is None:
        raise HTTPException(status_code=409, detail="report is not available until the current run stops")
    path = info.report.markdown_path if format == "markdown" else info.report.json_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="report artifact is unavailable")
    media_type = "text/markdown; charset=utf-8" if format == "markdown" else "application/json"
    return FileResponse(path, media_type=media_type, filename=path.name)


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


# Mounted last so it never shadows the API routes above: Starlette matches routes in
# registration order, and this Mount's prefix ("/") would otherwise catch everything.
# `html=True` serves public/index.html for "/" and any other unmatched path.
app.mount("/", StaticFiles(directory=PUBLIC_DIR, html=True), name="public")
