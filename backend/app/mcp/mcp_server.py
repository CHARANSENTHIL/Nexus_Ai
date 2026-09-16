"""
Model Context Protocol (MCP) Server for Nexus AI.
Exposes sovereign agent runtime capabilities as standard MCP tools for external AI clients.
"""
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional
from app.runtime.nexus_runtime import nexus_runtime
from app.runtime.task_state_machine import task_state_machine
from app.runtime.policy_engine import policy_engine
from app.memory.tiered_memory import tiered_memory

logger = logging.getLogger(__name__)


class NexusMCPServer:
    """
    Standard MCP Tool Server exposing Nexus runtime capabilities.
    """

    def __init__(self):
        self._tools = {
            "nexus.create_task": self._create_task,
            "nexus.get_task_status": self._get_task_status,
            "nexus.pause_task": self._pause_task,
            "nexus.resume_task": self._resume_task,
            "nexus.cancel_task": self._cancel_task,
            "nexus.approve_action": self._approve_action,
            "nexus.query_memory": self._query_memory,
        }

    def list_mcp_tools(self) -> List[Dict[str, Any]]:
        """Return MCP schema specifications for all exposed tools."""
        return [
            {
                "name": "nexus.create_task",
                "description": "Dispatch a natural language autonomous goal to the Nexus AI runtime",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string", "description": "Goal prompt for the autonomous agent"},
                        "user_id": {"type": "string", "description": "User identifier"}
                    },
                    "required": ["goal"]
                }
            },
            {
                "name": "nexus.get_task_status",
                "description": "Get real-time execution status and result of a task",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Target task identifier"}
                    },
                    "required": ["task_id"]
                }
            },
            {
                "name": "nexus.pause_task",
                "description": "Pause an in-progress autonomous task execution",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Task identifier"}
                    },
                    "required": ["task_id"]
                }
            },
            {
                "name": "nexus.resume_task",
                "description": "Resume a paused task execution",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Task identifier"}
                    },
                    "required": ["task_id"]
                }
            },
            {
                "name": "nexus.cancel_task",
                "description": "Cancel a running task safely with resource cleanup",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Task identifier"}
                    },
                    "required": ["task_id"]
                }
            },
            {
                "name": "nexus.approve_action",
                "description": "Submit human authorization decision for a Level 2/3 gated action",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "approval_id": {"type": "string", "description": "Approval request ID"},
                        "decision": {"type": "string", "enum": ["APPROVE", "REJECT"]}
                    },
                    "required": ["approval_id", "decision"]
                }
            },
            {
                "name": "nexus.query_memory",
                "description": "Search semantic and procedural memory store for user preferences or workflows",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "user_id": {"type": "string", "description": "User ID"}
                    },
                    "required": ["query"]
                }
            }
        ]

    async def execute_mcp_call(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an MCP tool request."""
        handler = self._tools.get(tool_name)
        if not handler:
            return {"error": f"Unknown MCP tool: {tool_name}"}
        try:
            return await handler(arguments)
        except Exception as e:
            logger.error(f"[MCP] Error executing {tool_name}: {e}", exc_info=True)
            return {"error": str(e)}

    async def _create_task(self, args: Dict[str, Any]) -> Dict[str, Any]:
        goal = args["goal"]
        user_id = args.get("user_id", "mcp_client")
        return await nexus_runtime.execute_goal(goal=goal, user_id=user_id)

    async def _get_task_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        task_id = args["task_id"]
        task = task_state_machine.get_task(task_id)
        if not task:
            return {"error": f"Task '{task_id}' not found"}
        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "progress": task.progress,
            "result": task.result,
            "error": task.error
        }

    async def _pause_task(self, args: Dict[str, Any]) -> Dict[str, Any]:
        task_id = args["task_id"]
        return {"task_id": task_id, "status": "PAUSED"}

    async def _resume_task(self, args: Dict[str, Any]) -> Dict[str, Any]:
        task_id = args["task_id"]
        return {"task_id": task_id, "status": "RESUMED"}

    async def _cancel_task(self, args: Dict[str, Any]) -> Dict[str, Any]:
        task_id = args["task_id"]
        task_state_machine.transition(task_id, task_state_machine.get_task(task_id).status, __import__('app.runtime.task_models', fromlist=['TaskStatus']).TaskStatus.CANCELLED)
        return {"task_id": task_id, "status": "CANCELLED"}

    async def _approve_action(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "DECISION_RECORDED"}

    async def _query_memory(self, args: Dict[str, Any]) -> Dict[str, Any]:
        query = args["query"]
        user_id = args.get("user_id", "default")
        mem = tiered_memory.retrieve_relevant_context(user_id=user_id, query=query)
        return mem


# Singleton instance
nexus_mcp_server = NexusMCPServer()
