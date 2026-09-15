"""
Nexus Runtime — Central Execution Gateway & Unified Agent Runtime.
Every goal from Telegram, Voice, or Web flows through this single runtime pipeline:
  Gateway -> Task State Machine -> Planner -> Policy Engine -> Tool Registry -> Verification -> Recovery.
"""
import time
import asyncio
import inspect
import logging
from typing import Dict, Any, Optional, Callable, List

from app.runtime.task_models import (
    TaskState,
    CapabilityLevel,
    TaskRecord,
    SubtaskNode,
)
from app.runtime.task_state_machine import task_state_machine, TaskStateMachine
from app.runtime.policy_engine import policy_engine, PolicyEngine
from app.runtime.tool_registry import tool_registry, ToolRegistry
from app.runtime.observation_verifier import observation_verifier, ObservationVerifier
from app.runtime.recovery_engine import recovery_engine, RecoveryEngine
from app.handoff.handoff_engine import handoff_engine
from app.handoff.handoff_models import HandoffTrigger

logger = logging.getLogger(__name__)


class NexusRuntime:
    """
    Central execution runtime providing unified state, security gating, tool dispatch,
    observation verification, and bounded self-healing.
    """

    def __init__(self):
        self.state_machine = task_state_machine
        self.policy = policy_engine
        self.tools = tool_registry
        self.verifier = observation_verifier
        self.recovery = recovery_engine
        self._progress_callbacks: List[Callable] = []

    def register_progress_callback(self, callback_fn: Callable):
        """Register listener for live progress updates async fn(task_id, message, state)."""
        self._progress_callbacks.append(callback_fn)

    async def _emit_progress(self, task: TaskRecord, message: str):
        for cb in self._progress_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(task.task_id, message, task.state.value)
                else:
                    cb(task.task_id, message, task.state.value)
            except Exception as e:
                logger.warning(f"[Runtime] Progress callback error: {e}")

    async def execute_goal(
        self,
        goal: str,
        user_id: str,
        approval_notifier: Optional[Callable] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TaskRecord:
        """
        Main entrypoint: executes a natural language goal through the unified runtime.
        """
        # 1. Create durable task record (State: CREATED)
        task = self.state_machine.create_task(goal=goal, user_id=user_id, metadata=metadata)
        logger.info(f"[Runtime] 🚀 Initialized Task {task.task_id} for user {user_id}")
        await self._emit_progress(task, f"Task created: {goal[:60]}")

        # 2. Decompose Goal via Planner (State: PLANNING)
        self.state_machine.transition_state(task, TaskState.PLANNING)
        from app.agents.planner import planner_agent, IntentRouter

        # Check intent fast-path or LLM decomposition
        planned_subtasks = IntentRouter.detect(goal)
        if not planned_subtasks:
            # Fallback to planner LLM decomposition
            plan_obj = await planner_agent.plan_goal(goal, user_id=user_id)
            planned_subtasks = [
                {
                    "title": node.description,
                    "description": node.description,
                    "tool": node.input_data.get("tool", ""),
                    "tool_input": node.input_data.get("tool_input", {}),
                    "agent": node.assigned_agent,
                }
                for node in plan_obj.task_graph.nodes.values()
            ]

        # Convert to SubtaskNodes
        subtask_nodes = []
        for i, st in enumerate(planned_subtasks):
            tool_name = st.get("tool", "")
            tool_def = self.tools.get_tool(tool_name)
            cap_level = tool_def.capability_level if tool_def else CapabilityLevel.LEVEL_1_SAFE_WRITE
            req_approval = tool_def.requires_approval if tool_def else False

            node = SubtaskNode(
                subtask_id=f"{task.task_id}_sub_{i+1}",
                title=st.get("title", tool_name),
                description=st.get("description", tool_name),
                tool_name=tool_name,
                tool_input=st.get("tool_input", {}),
                assigned_agent=st.get("agent", "general"),
                capability_level=cap_level,
                requires_approval=req_approval,
            )
            subtask_nodes.append(node)

        task.subtasks = subtask_nodes
        task.total_steps = len(subtask_nodes)
        self.state_machine.save_task(task)

        # 3. Execute Subtasks Sequentially
        self.state_machine.transition_state(task, TaskState.EXECUTING)

        for idx, subtask in enumerate(task.subtasks):
            task.current_subtask_index = idx
            subtask.state = TaskState.EXECUTING
            self.state_machine.save_task(task)

            tool_def = self.tools.get_tool(subtask.tool_name)
            if not tool_def:
                subtask.state = TaskState.FAILED
                subtask.error = f"Unregistered tool: '{subtask.tool_name}'"
                self.state_machine.transition_state(task, TaskState.FAILED, error=subtask.error)
                return task

            # A. Policy Engine Pre-Execution Check
            is_allowed, cap_level, req_approval, reason = self.policy.evaluate_execution(
                tool=tool_def,
                tool_input=subtask.tool_input,
                user_id=user_id,
            )

            if not is_allowed:
                subtask.state = TaskState.FAILED
                subtask.error = f"Policy Engine BLOCKED execution: {reason}"
                self.state_machine.transition_state(task, TaskState.FAILED, error=subtask.error)
                return task

            # B. Human Approval Gating for Sensitive/Destructive actions
            if req_approval:
                self.state_machine.transition_state(task, TaskState.AWAITING_APPROVAL)
                await self._emit_progress(task, f"⚠️ Action '{subtask.title}' requires approval.")
                
                from app.approval.executor import approval_center
                approved = await approval_center.request_approval(
                    user_id=user_id,
                    action_type=subtask.tool_name,
                    details={"title": subtask.title, "input": subtask.tool_input},
                    notify_fn=approval_notifier or (lambda u, m, a: None),
                )
                if not approved:
                    subtask.state = TaskState.CANCELLED
                    subtask.error = "Action rejected by user."
                    self.state_machine.transition_state(task, TaskState.CANCELLED, error=subtask.error)
                    return task
                self.state_machine.transition_state(task, TaskState.EXECUTING)

            # C. Bounded Execution & Self-Healing Loop (Max 3 Attempts)
            max_attempts = 3
            subtask_success = False

            for attempt in range(1, max_attempts + 1):
                subtask.attempts = attempt
                start_t = time.time()
                try:
                    # Execute tool function with timeout
                    fn_to_call = tool_def.execute_fn
                    if inspect.iscoroutinefunction(fn_to_call):
                        raw_result = await asyncio.wait_for(fn_to_call(**subtask.tool_input), timeout=tool_def.timeout_seconds)
                    else:
                        raw_result = await asyncio.to_thread(fn_to_call, **subtask.tool_input)

                    subtask.execution_duration_ms = (time.time() - start_t) * 1000
                    subtask.result = raw_result

                    # D. Action -> Observation -> Verification
                    self.state_machine.transition_state(task, TaskState.VERIFYING)
                    verification = await self.verifier.verify(
                        strategy=tool_def.verification_strategy,
                        tool_name=subtask.tool_name,
                        tool_input=subtask.tool_input,
                        raw_result=raw_result,
                    )
                    subtask.verification_passed = verification.passed
                    subtask.verification_notes = verification.details

                    if verification.passed:
                        subtask.state = TaskState.COMPLETED
                        subtask_success = True
                        task.completed_steps_count += 1
                        self.state_machine.save_task(task)
                        logger.info(f"[Runtime] ✅ Subtask {subtask.subtask_id} verified: {verification.details}")
                        break
                    else:
                        raise ValueError(f"Action verification failed: {verification.details}")

                except Exception as e:
                    subtask.error = str(e)
                    logger.warning(f"[Runtime] Subtask {subtask.subtask_id} failed attempt {attempt}: {e}")

                    # Error Classification & Recovery
                    err_cat = self.recovery.classify_error(str(e), subtask.tool_name)
                    can_recover, strat_desc, plan = self.recovery.determine_recovery(
                        category=err_cat,
                        attempt=attempt,
                        max_retries=max_attempts,
                        details={"error": str(e), "input": subtask.tool_input}
                    )

                    if can_recover:
                        self.state_machine.transition_state(task, TaskState.RETRYING)
                        await self._emit_progress(task, f"🔧 Recovering ({strat_desc})...")
                        if plan and plan.get("action") == "retry_backoff":
                            await asyncio.sleep(plan.get("backoff_seconds", 2))
                    else:
                        # Escalate to Human Handoff
                        self.state_machine.transition_state(task, TaskState.WAITING_FOR_HUMAN)
                        cp = await handoff_engine.trigger_handoff(
                            task_id=task.task_id,
                            user_id=user_id,
                            agent_name=subtask.assigned_agent,
                            trigger=HandoffTrigger.LOW_CONFIDENCE,
                            reason=f"Subtask failed after recovery: {e}",
                        )
                        resolved_cp = await handoff_engine.wait_for_resolution(cp.checkpoint_id)
                        if resolved_cp.state == TaskState.RESUMED:
                            self.state_machine.transition_state(task, TaskState.EXECUTING)
                            subtask_success = True
                            break
                        else:
                            break

            if not subtask_success:
                subtask.state = TaskState.FAILED
                self.state_machine.transition_state(task, TaskState.FAILED, error=subtask.error)
                return task

        # 4. Final Verification & Completion
        task.final_output = f"Completed {task.completed_steps_count}/{task.total_steps} steps successfully."
        self.state_machine.transition_state(task, TaskState.COMPLETED)
        logger.info(f"[Runtime] 🎉 Task {task.task_id} COMPLETED SUCCESSFULLY.")
        return task


# Singleton instance
nexus_runtime = NexusRuntime()
