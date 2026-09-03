"""
Screen Action Memory & Telemetry Engine for Nexus AI.
Tracks before/after action states, expected vs actual outcomes,
success/failure rates, retries, and vision accuracy metrics.
"""
import time
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ScreenActionMemory:
    """Telemetry logger and metrics calculator for screen action loops."""

    def __init__(self):
        self.action_history: List[Dict[str, Any]] = []
        self.task_history: List[Dict[str, Any]] = []

    def record_action(
        self,
        task_id: str,
        action: str,
        target: str,
        expected: str,
        actual: str,
        success: bool,
        duration_ms: float = 0.0,
        retry_count: int = 0,
    ) -> Dict[str, Any]:
        """Record an individual micro-action attempt."""
        entry = {
            "action_id": f"act_{len(self.action_history) + 1}",
            "task_id": task_id,
            "action": action,
            "target": target,
            "expected": expected,
            "actual": actual,
            "success": success,
            "duration_ms": duration_ms,
            "retry_count": retry_count,
            "timestamp": datetime.now().isoformat(),
        }
        self.action_history.append(entry)
        logger.info(f"[ScreenMemory] Action recorded: {action} on '{target}' -> Success: {success}")
        return entry

    def record_task_summary(
        self,
        task_id: str,
        goal: str,
        total_steps: int,
        successful_steps: int,
        retries: int,
        final_success: bool,
    ) -> Dict[str, Any]:
        """Record an overall screen loop task summary."""
        summary = {
            "task_id": task_id,
            "goal": goal,
            "total_steps": total_steps,
            "successful_steps": successful_steps,
            "retries": retries,
            "final_success": final_success,
            "timestamp": datetime.now().isoformat(),
        }
        self.task_history.append(summary)
        return summary

    def get_telemetry_metrics(self) -> Dict[str, Any]:
        """
        Calculate telemetry metrics for the dashboard:
        - task_success_rate (%)
        - action_failure_rate (%)
        - average_retries
        - vision_accuracy (%)
        """
        total_tasks = len(self.task_history)
        total_actions = len(self.action_history)

        if total_tasks == 0:
            task_success_rate = 100.0
            avg_retries = 0.0
        else:
            successful_tasks = sum(1 for t in self.task_history if t.get("final_success", False))
            task_success_rate = round((successful_tasks / total_tasks) * 100.0, 1)
            total_retries = sum(t.get("retries", 0) for t in self.task_history)
            avg_retries = round(total_retries / total_tasks, 2)

        if total_actions == 0:
            action_failure_rate = 0.0
            vision_accuracy = 100.0
        else:
            failed_actions = sum(1 for a in self.action_history if not a.get("success", False))
            action_failure_rate = round((failed_actions / total_actions) * 100.0, 1)
            vision_accuracy = round(100.0 - action_failure_rate, 1)

        return {
            "total_tasks": total_tasks,
            "total_actions": total_actions,
            "task_success_rate": task_success_rate,
            "action_failure_rate": action_failure_rate,
            "average_retries": avg_retries,
            "vision_accuracy": vision_accuracy,
            "recent_actions": self.action_history[-10:],
            "recent_tasks": self.task_history[-5:],
        }


# Singleton instance
screen_memory = ScreenActionMemory()
