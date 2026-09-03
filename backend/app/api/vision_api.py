"""
Vision & Computer Agent API Router — /api/v1/vision/telemetry & execute-loop.
Exposes real-time screen action telemetry, metrics, and closed-loop execution to the dashboard.
"""
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.vision.screen_action_memory import screen_memory
from app.vision.computer_agent import computer_agent

logger = logging.getLogger(__name__)
router = APIRouter()


class ScreenLoopRequest(BaseModel):
    goal: str
    max_steps: int = 5
    user_id: str = "api_user"


@router.get("/vision/telemetry")
async def get_vision_telemetry():
    """Return real-time Computer Agent telemetry metrics for dashboard visualization."""
    return screen_memory.get_telemetry_metrics()


@router.post("/vision/execute-loop")
async def execute_screen_loop(request: ScreenLoopRequest):
    """Trigger an autonomous Observer-Executor screen understanding loop."""
    try:
        res = await computer_agent.run_screen_loop(
            goal=request.goal,
            max_steps=request.max_steps,
            user_id=request.user_id,
        )
        return res
    except Exception as e:
        logger.error(f"[VisionAPI] Loop execution error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
