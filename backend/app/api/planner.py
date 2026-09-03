"""
Planner API — POST /api/v1/planner/execute
Accepts natural language goals, runs the CrewAI pipeline, returns results.
Also exposes the audit log and approval endpoints.
"""
import asyncio
import time
import uuid
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from app.agents.planner import planner_agent
from app.approval.executor import approval_center, get_audit_log
from app.auth.jwt import verify_token

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return payload


# ── Request / Response models ─────────────────────────────────────────────────
class PlannerRequest(BaseModel):
    goal: str
    context: Dict[str, Any] = {}
    user_id: str = "api_user"


class PlannerResponse(BaseModel):
    task_id: str
    status: str
    subtasks: list
    result: Dict[str, Any]
    execution_time_seconds: float


class ApprovalAction(BaseModel):
    approval_id: str
    approved: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────
@router.post("/planner/execute", response_model=PlannerResponse)
async def execute_goal(request: PlannerRequest, user=Depends(get_current_user)):
    """Decompose a natural language goal and execute it via the CrewAI agent pipeline."""
    task_id = str(uuid.uuid4())
    start = time.time()

    try:
        from app.agents.langgraph_orchestrator import execute_nexus_graph
        graph_result = await execute_nexus_graph(request.goal, user_id=request.user_id)
        
        elapsed = round(time.time() - start, 2)
        return PlannerResponse(
            task_id=task_id,
            status="completed",
            subtasks=graph_result.get("results", []),
            result={
                "summary": graph_result.get("final_output", ""),
                "intent": graph_result.get("intent", ""),
                "route": graph_result.get("route", ""),
                "domain": graph_result.get("domain", ""),
            },
            execution_time_seconds=elapsed,
        )


    except Exception as e:
        elapsed = round(time.time() - start, 2)
        logger.error(f"Planner execute error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/planner/audit-log")
async def get_audit(limit: int = 50):
    """Return the last N audit log entries."""
    return {"audit_log": get_audit_log(limit=limit)}


@router.get("/planner/pending-approvals")
async def list_pending():
    """List all currently pending approval requests."""
    return {"pending": approval_center.get_pending()}


@router.post("/planner/resolve-approval")
async def resolve_approval(action: ApprovalAction):
    """Resolve an approval request (approve or reject) from the dashboard UI."""
    approval_center.resolve_approval(action.approval_id, action.approved)
    return {"resolved": True, "approval_id": action.approval_id, "approved": action.approved}
