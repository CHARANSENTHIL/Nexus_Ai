"""
FastAPI Router for n8n Automation Layer Integration.
Exposes endpoints for n8n Webhook, HTTP Request, Schedule, and Human-in-the-Loop Approval nodes.
"""
import os
import sys
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, BackgroundTasks, status

from app.computer_use.interface import computer
from app.computer_use.models import ActionRequest, ActionResult, ActionType, ExecutionMethod
from app.events.event_bus import event_bus
from app.events.event_models import NexusEvent, EventType
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

N8N_WORKFLOWS_DIR = os.path.abspath(r"D:\nexus_ai\n8n\workflows")


# ── Pydantic Request/Response Models ──────────────────────────────────────────

class PCHealthResponse(BaseModel):
    status: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    cpu_percent: float
    ram_percent: float
    disk_percent: float
    battery_percent: Optional[float] = None
    active_window: str
    top_processes: List[Dict[str, Any]]
    is_abnormal: bool
    warnings: List[str]


class PCExecuteRequest(BaseModel):
    action: str
    target: Optional[str] = None
    text_val: Optional[str] = None
    amount: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AIAnalyzeRequest(BaseModel):
    context_type: str  # "pc_health", "incident", "github_issue", "daily_summary"
    data: Dict[str, Any]
    instruction: Optional[str] = None


class AIAnalyzeResponse(BaseModel):
    summary: str
    severity: str  # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    recommendations: List[str]
    suggested_actions: List[Dict[str, Any]]


class GitHubWebhookPayload(BaseModel):
    action: str
    issue: Optional[Dict[str, Any]] = None
    repository: Optional[Dict[str, Any]] = None
    sender: Optional[Dict[str, Any]] = None


class ApprovalRequestPayload(BaseModel):
    task_id: str
    action_type: str
    target: str
    risk_level: str
    reason: str


class ApprovalResponsePayload(BaseModel):
    task_id: str
    approved: bool
    approved_by: str = "telegram_user"
    feedback: Optional[str] = None


# ── 1. PC Health Endpoint (for n8n Schedule Trigger) ──────────────────────────

@router.post("/pc/health", response_model=PCHealthResponse)
async def get_pc_health_for_n8n():
    """
    Called by n8n HTTP Request node on a schedule or trigger.
    Returns comprehensive hardware telemetry, active window, and abnormal state flags.
    """
    import psutil

    cpu = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory().percent
    disk = psutil.disk_usage("C:\\").percent
    battery = None
    if hasattr(psutil, "sensors_battery"):
        bat = psutil.sensors_battery()
        battery = bat.percent if bat else None

    # Get active window
    window_res = await computer.get_active_window()
    active_win = str(window_res.output or "Desktop")

    # Get top 5 CPU processes
    top_procs = []
    for proc in sorted(psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]),
                       key=lambda p: p.info.get("cpu_percent") or 0, reverse=True)[:5]:
        top_procs.append({
            "pid": proc.info["pid"],
            "name": proc.info["name"],
            "cpu_percent": proc.info.get("cpu_percent", 0),
            "ram_percent": round(proc.info.get("memory_percent", 0), 1),
        })

    # Evaluation
    warnings = []
    if disk >= 85:
        warnings.append(f"Disk usage is critical ({disk}%)")
    if ram >= 90:
        warnings.append(f"RAM usage is high ({ram}%)")
    if cpu >= 90:
        warnings.append(f"CPU load is heavy ({cpu}%)")

    is_abnormal = len(warnings) > 0
    status_str = "warning" if is_abnormal else "healthy"

    return PCHealthResponse(
        status=status_str,
        cpu_percent=cpu,
        ram_percent=ram,
        disk_percent=disk,
        battery_percent=battery,
        active_window=active_win,
        top_processes=top_procs,
        is_abnormal=is_abnormal,
        warnings=warnings,
    )


# ── 2. PC Execute Endpoint (for n8n to call ComputerInterface) ─────────────────

@router.post("/pc/execute", response_model=ActionResult)
async def execute_pc_action_from_n8n(req: PCExecuteRequest):
    """
    Execute a semantic action via the Computer Use Abstraction Layer.
    n8n uses this to launch apps, change volume, navigate browsers, or run scripts.
    """
    try:
        action_enum = ActionType(req.action.lower())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid action '{req.action}'. Valid options: {[a.value for a in ActionType]}"
        )

    action_request = ActionRequest(
        action=action_enum,
        target=req.target,
        text_val=req.text_val,
        amount=req.amount,
        metadata=req.metadata,
    )

    result = await computer.execute_action(action_request)
    return result


# ── 3. AI Analysis & Diagnosis Endpoint ───────────────────────────────────────

@router.post("/agent/analyze", response_model=AIAnalyzeResponse)
async def analyze_with_ai(req: AIAnalyzeRequest):
    """
    Analyzes telemetry, incident data, or external webhook payloads using local LLM heuristics.
    Returns structured recommendations and suggested actions for n8n to route.
    """
    context_type = req.context_type
    data = req.data

    if context_type == "pc_health":
        cpu = data.get("cpu_percent", 0)
        ram = data.get("ram_percent", 0)
        disk = data.get("disk_percent", 0)

        warnings = data.get("warnings", [])
        if warnings:
            summary = f"Abnormal PC state detected: {', '.join(warnings)}."
            severity = "HIGH" if disk >= 90 or ram >= 95 else "MEDIUM"
            recommendations = [
                "Clean temporary directories in %TEMP% and cache folders",
                "Close background memory-heavy tabs or idle processes"
            ]
            suggested_actions = [
                {"action": "open_app", "target": "taskmgr"}
            ]
        else:
            summary = f"All systems operating within optimal thresholds (CPU: {cpu}%, RAM: {ram}%, Disk: {disk}%)."
            severity = "LOW"
            recommendations = ["No action required. Normal operational state."]
            suggested_actions = []

    elif context_type == "incident":
        error_msg = data.get("error", "Unknown process error")
        summary = f"Incident Alert: Process error '{error_msg}' identified."
        severity = "HIGH"
        recommendations = ["Restart affected daemon service", "Verify port bindings and local firewall"]
        suggested_actions = [{"action": "run_command", "target": "tasklist"}]

    elif context_type == "github_issue":
        title = data.get("title", "GitHub Issue")
        body = data.get("body", "")
        summary = f"GitHub Issue received: '{title}'"
        severity = "MEDIUM"
        recommendations = ["Spawn developer workspace and run regression test suite"]
        suggested_actions = [{"action": "open_app", "target": "code"}]

    else:
        summary = f"Processed {context_type} workflow data successfully."
        severity = "LOW"
        recommendations = ["Routine execution logged."]
        suggested_actions = []

    return AIAnalyzeResponse(
        summary=summary,
        severity=severity,
        recommendations=recommendations,
        suggested_actions=suggested_actions,
    )


# ── 4. External GitHub Webhook Bridge ─────────────────────────────────────────

@router.post("/webhook/github-event")
async def handle_github_webhook(payload: GitHubWebhookPayload, background_tasks: BackgroundTasks):
    """
    Receives GitHub webhooks forwarded from n8n.
    Emits an internal TASK_CREATED event to activate local autonomous coding agents.
    """
    action = payload.action
    issue = payload.issue or {}
    repo = payload.repository or {}

    title = issue.get("title", "External GitHub Event")
    body = issue.get("body", "")
    repo_name = repo.get("full_name", "unknown/repo")

    logger.info(f"[n8n Bridge] Received GitHub webhook for {repo_name} (Action: {action}, Title: '{title}')")

    # Publish to EventBus
    import uuid
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    event = NexusEvent(
        event_type=EventType.TASK_CREATED,
        task_id=task_id,
        source_agent="n8n_github_bridge",
        payload={
            "command": f"Investigate and fix GitHub issue '{title}': {body}",
            "task_type": "developer_workflow",
            "repository": repo_name,
            "github_action": action,
        }
    )
    background_tasks.add_task(event_bus.publish, event)

    return {
        "status": "accepted",
        "task_id": task_id,
        "message": f"GitHub issue '{title}' dispatched to AI Core",
    }


# ── 5. Human-in-the-Loop Approval Hub ──────────────────────────────────────────

@router.post("/approval/request")
async def create_approval_request(payload: ApprovalRequestPayload):
    """
    Submits a high-risk action to n8n approval workflow.
    """
    event = NexusEvent(
        event_type=EventType.APPROVAL_REQUIRED,
        source_agent="security_engine",
        task_id=payload.task_id,
        payload={
            "action": payload.action_type,
            "target": payload.target,
            "risk_level": payload.risk_level,
            "reason": payload.reason,
        }
    )
    await event_bus.publish(event)
    return {
        "status": "pending_approval",
        "task_id": payload.task_id,
        "risk_level": payload.risk_level,
    }


@router.post("/approval/response")
async def handle_approval_response(payload: ApprovalResponsePayload):
    """
    Receives user decision from n8n Telegram / Slack approval button.
    """
    event_type = EventType.ACTION_APPROVED if payload.approved else EventType.ACTION_BLOCKED
    event = NexusEvent(
        event_type=event_type,
        source_agent="n8n_approval_hook",
        task_id=payload.task_id,
        payload={
            "approved": payload.approved,
            "approved_by": payload.approved_by,
            "feedback": payload.feedback,
        }
    )
    await event_bus.publish(event)
    return {
        "status": "processed",
        "task_id": payload.task_id,
        "decision": "APPROVED" if payload.approved else "DENIED",
    }



# ── 6. Workflow Marketplace Listing ───────────────────────────────────────────

@router.get("/workflows")
async def list_available_workflows():
    """
    Returns the workflow marketplace listing available to the AI Core.
    """
    if not os.path.exists(N8N_WORKFLOWS_DIR):
        return {"workflows": []}

    workflows = []
    for file in os.listdir(N8N_WORKFLOWS_DIR):
        if file.endswith(".json"):
            file_path = os.path.join(N8N_WORKFLOWS_DIR, file)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    workflows.append({
                        "id": file[:-5],
                        "name": data.get("name", file[:-5]),
                        "filename": file,
                        "nodes_count": len(data.get("nodes", [])),
                    })
            except Exception:
                pass

    return {"count": len(workflows), "workflows": workflows}
