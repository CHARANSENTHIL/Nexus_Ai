from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, ConfigDict

class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    AWAITING_APPROVAL = "awaiting_approval"

class AgentType(str, Enum):
    PLANNER = "planner"
    SYSTEM = "system"
    APPLICATION = "application"
    FILE = "file"
    VISION = "vision"

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class TaskNode(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(..., description="Unique subtask node identifier")
    title: str = Field(..., description="Short summary title of the subtask")
    description: str = Field(..., description="Detailed execution prompt or instruction")
    assigned_agent: AgentType = Field(..., description="Target specialized agent responsible for execution")
    dependencies: List[str] = Field(default_factory=list, description="Node IDs that must complete before this node can run")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Current execution state")
    input_data: Dict[str, Any] = Field(default_factory=dict, description="Context/parameters for execution")
    output_data: Optional[Dict[str, Any]] = Field(default=None, description="Results produced upon completion")
    error: Optional[str] = Field(default=None, description="Failure details if status is FAILED")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class TaskGraph(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    graph_id: str = Field(..., description="Unique task graph identifier")
    goal: str = Field(..., description="Original user prompt or top-level goal")
    nodes: Dict[str, TaskNode] = Field(default_factory=dict, description="Map of node_id -> TaskNode")
    execution_order: List[str] = Field(default_factory=list, description="Topologically sorted node IDs for execution")
    is_completed: bool = Field(default=False, description="Flag indicating full graph execution completion")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def get_ready_nodes(self) -> List[TaskNode]:
        ready = []
        for node_id in self.execution_order:
            node = self.nodes.get(node_id)
            if not node or node.status != TaskStatus.PENDING:
                continue
            deps_satisfied = all(
                self.nodes.get(dep_id) and self.nodes[dep_id].status == TaskStatus.COMPLETED
                for dep_id in node.dependencies
            )
            if deps_satisfied:
                ready.append(node)
        return ready

    def mark_node_status(self, node_id: str, status: TaskStatus, output_data: Optional[Dict[str, Any]] = None, error: Optional[str] = None):
        if node_id in self.nodes:
            node = self.nodes[node_id]
            node.status = status
            if output_data is not None:
                node.output_data = output_data
            if error is not None:
                node.error = error
            node.updated_at = datetime.now(timezone.utc)
            self.updated_at = datetime.now(timezone.utc)
            self.is_completed = all(n.status == TaskStatus.COMPLETED for n in self.nodes.values())

class SubtaskExecutionPlan(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    plan_id: str = Field(..., description="Unique plan identifier")
    goal: str = Field(..., description="High level goal description")
    task_graph: TaskGraph = Field(..., description="The planned DAG execution graph")
    estimated_steps: int = Field(..., description="Total number of steps in plan")
    risk_level: RiskLevel = Field(default=RiskLevel.LOW, description="Overall security risk level")
    requires_approval: bool = Field(default=False, description="True if any subtask requires approval")
    approval_actions: List[str] = Field(default_factory=list, description="List of subtasks requiring approval")

class TaskRequest(BaseModel):
    request_id: str = Field(..., description="Unique incoming request ID")
    user_id: str = Field(..., description="User ID issuing request")
    project_id: str = Field(default="default", description="Project namespace identifier")
    session_id: str = Field(default="default", description="Session identifier")
    goal: str = Field(..., description="Natural language request or command")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context parameters")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class TaskResponse(BaseModel):
    response_id: str = Field(..., description="Unique response ID")
    request_id: str = Field(..., description="Matching task request ID")
    status: str = Field(..., description="Final execution outcome")
    task_graph: Optional[TaskGraph] = Field(default=None, description="Executed TaskGraph state")
    execution_summary: str = Field(..., description="Human readable summary")
    results: Dict[str, Any] = Field(default_factory=dict, description="Aggregated node outputs")
    execution_time_seconds: float = Field(default=0.0, description="Total runtime in seconds")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class AgentActionResult(BaseModel):
    action_id: str = Field(..., description="Unique action execution identifier")
    node_id: str = Field(..., description="TaskNode ID associated with this action")
    agent_name: AgentType = Field(..., description="Executing agent identifier")
    action_type: str = Field(..., description="Specific tool action performed")
    status: TaskStatus = Field(..., description="Result status")
    result_data: Dict[str, Any] = Field(default_factory=dict, description="Output payload from tool")
    error_message: Optional[str] = Field(default=None, description="Error detail if action failed")
    execution_duration: float = Field(default=0.0, description="Duration in seconds")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
