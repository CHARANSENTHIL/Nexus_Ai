"""
Events API: Real-time Event Stream (SSE) & Task Timeline Endpoints for Next.js Dashboard.
"""
import asyncio
import json
import logging
from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.events.event_bus import event_bus
from app.events.task_tracker import task_tracker

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Events & Timeline"])


@router.get("/events/timeline/{task_id}", response_model=List[Dict[str, Any]])
async def get_task_timeline(task_id: str):
    """
    Returns the complete chronological event timeline for a task.
    """
    events = await task_tracker.get_task_timeline(task_id)
    if not events:
        raise HTTPException(status_code=404, detail=f"No event timeline found for task '{task_id}'")
    return events


@router.get("/events/state/{task_id}")
async def get_task_state(task_id: str):
    """
    Returns the current state snapshot of an event-driven task.
    """
    state = await task_tracker.get_task_state(task_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return state


@router.get("/events/stream/{task_id}")
async def stream_task_events(task_id: str, poll_interval: float = Query(0.2, ge=0.05, le=2.0)):
    """
    Server-Sent Events (SSE) stream for live timeline updates on the Next.js frontend.
    """
    async def event_generator():
        last_count = 0
        timeout = 120.0
        start_time = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            events = await task_tracker.get_task_timeline(task_id)
            if len(events) > last_count:
                for evt in events[last_count:]:
                    yield f"data: {json.dumps(evt)}\n\n"
                last_count = len(events)

                # Check if task is finished
                state = await task_tracker.get_task_state(task_id)
                if state and state.get("status") in ("COMPLETED", "FAILED", "TIMEOUT"):
                    yield f"data: {json.dumps({'event_type': 'STREAM_END', 'status': state.get('status')})}\n\n"
                    break

            await asyncio.sleep(poll_interval)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
