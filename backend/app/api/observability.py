"""
Runtime Observability API Router — Exposes live task event streams, lock states, and metrics.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any, List, Optional
from app.runtime.event_log import execution_event_log
from app.runtime.resource_locks import resource_lock_manager
from app.runtime.model_router import model_router
from app.runtime.task_state_machine import task_state_machine

router = APIRouter(prefix="/api/observability", tags=["Observability"])


@router.get("/events/metrics")
async def get_event_metrics() -> Dict[str, Any]:
    """Get global event counts and type distribution."""
    return execution_event_log.get_event_metrics()


@router.get("/events/task/{task_id}")
async def get_task_timeline(task_id: str) -> List[Dict[str, Any]]:
    """Retrieve full chronological execution event log for a specific task."""
    events = execution_event_log.get_task_events(task_id)
    if not events:
        raise HTTPException(status_code=404, detail=f"No execution events found for task '{task_id}'")
    return events


@router.get("/resources/locks")
async def get_resource_locks() -> Dict[str, Any]:
    """Get current active resource lock allocations and holders."""
    return resource_lock_manager.get_lock_status()


@router.get("/hardware/status")
async def get_hardware_status() -> Dict[str, Any]:
    """Get real-time CPU, RAM, and model routing headroom."""
    return model_router.inspect_hardware_state()
