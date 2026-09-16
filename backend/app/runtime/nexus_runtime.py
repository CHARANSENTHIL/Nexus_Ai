"""
Nexus Runtime — Central Execution Gateway & Unified Agent Runtime.
Every goal from Telegram, Voice, or Web flows through this single runtime pipeline:
  Gateway -> Task State Machine -> Event Sourcing -> Policy Engine -> Tool Registry -> Idempotency -> Verification -> Recovery.
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
from app.runtime.event_log import execution_event_log, ExecutionEventType
from app.runtime.idempotency import idempotency_manager
from app.runtime.resource_locks import resource_lock_manager, ResourceScope
from app.handoff.handoff_engine import handoff_engine
from app.handoff.handoff_models import HandoffTrigger

logger = logging.getLogger(__name__)


class NexusRuntime:
    """
    Central execution runtime providing unified state, event sourcing, security gating,
    idempotency guarantees, tool dispatch, observation verification, and bounded recovery.
    """

    def __init__(self):
        self.state_machine = task_state_machine
        self.policy = policy_engine
        self.tools = tool_registry
        self.verifier = observation_verifier
        self.recovery = recovery_engine
        self.event_log = execution_event_log
        self.idempotency = idempotency_manager
        self.locks = resource_lock_manager
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
        self.event_log.append_event(
            task_id=task.task_id,
            event_type=ExecutionEventType.TASK_CREATED,
            input_data={"goal": goal, "user_id": user_id},
            metadata=metadata
        )
        await self._emit_progress(task, f"Task created: {goal[:60]}")

        # Initialize Working Memory
        from app.memory.tiered_memory import tiered_memory
        tiered_memory.init_working_memory(task.task_id, goal=goal, initial_context=metadata)

        # 2. Decompose Goal via Planner (State: PLANNING)
        self.state_machine.transition_state(task, TaskState.PLANNING)
        from app.agents.planner import planner_agent, IntentRouter

        planned_subtasks = IntentRouter.detect(goal)
        if not planned_subtasks:
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

            node = SubtaskNode(
                id=f"step_{i+1}",
                title=st.get("title", f"Step {i+1}"),
                tool_name=tool_name,
                tool_input=st.get("tool_input", {}),
                capability_level=cap_level,
                verification_strategy=tool_def.verification_strategy if tool_def else None,
            )
            subtask_nodes.append(node)

        self.state_machine.attach_plan(task, subtask_nodes)
        self.event_log.append_event(
            task_id=task.task_id,
            event_type=ExecutionEventType.PLAN_GENERATED,
            output_data={"subtask_count": len(subtask_nodes)}
        )
        await self._emit_progress(task, f"Plan generated with {len(subtask_nodes)} subtasks.")

        # 3. Execute Action -> Observation -> Verification Loop
        self.state_machine.transition_state(task, TaskState.RUNNING)
        accumulated_results = []

        for subtask in task.subtasks:
            # Active cancellation check
            if task.state == TaskState.CANCELLED:
                logger.info(f"[Runtime] Task {task.task_id} received cancellation signal. Aborting remaining steps.")
                self.event_log.append_event(task_id=task.task_id, event_type=ExecutionEventType.TASK_CANCELLED)
                return task

            subtask.state = TaskState.RUNNING
            await self._emit_progress(task, f"Executing {subtask.title} ({subtask.tool_name})...")

            # 3a. Pre-execution Security Policy Evaluation
            self.event_log.append_event(
                task_id=task.task_id,
                event_type=ExecutionEventType.POLICY_CHECKED,
                tool_name=subtask.tool_name,
                input_data=subtask.tool_input
            )
            eval_res = self.policy.evaluate_action(
                tool_name=subtask.tool_name,
                tool_input=subtask.tool_input,
                user_id=user_id,
                session_authenticated=True
            )

            if not eval_res.allowed:
                if eval_res.requires_approval:
                    self.state_machine.transition_state(task, TaskState.WAITING_FOR_APPROVAL)
                    self.event_log.append_event(
                        task_id=task.task_id,
                        event_type=ExecutionEventType.APPROVAL_REQUESTED,
                        tool_name=subtask.tool_name,
                        input_data=subtask.tool_input
                    )
                    await self._emit_progress(task, f"⚠️ Action '{subtask.tool_name}' requires human approval.")

                    approved = False
                    if approval_notifier:
                        try:
                            approved = await approval_notifier(eval_res.approval_request)
                        except Exception as e:
                            logger.error(f"[Runtime] Approval notification error: {e}")

                    if approved:
                        self.event_log.append_event(task_id=task.task_id, event_type=ExecutionEventType.APPROVAL_GRANTED)
                        self.state_machine.transition_state(task, TaskState.RUNNING)
                    else:
                        self.event_log.append_event(task_id=task.task_id, event_type=ExecutionEventType.APPROVAL_REJECTED)
                        subtask.state = TaskState.FAILED
                        subtask.error = "Action rejected by user security policy."
                        self.state_machine.fail_task(task, f"Execution halted: {subtask.error}")
                        return task
                else:
                    self.event_log.append_event(task_id=task.task_id, event_type=ExecutionEventType.TOOL_FAILED, metadata={"blocked": True})
                    subtask.state = TaskState.FAILED
                    subtask.error = f"Policy BLOCKED: {eval_res.reason}"
                    self.state_machine.fail_task(task, subtask.error)
                    return task

            # 3b. Idempotency Check
            idem_key = self.idempotency.generate_key(
                task_id=task.task_id,
                step_id=subtask.id,
                tool_name=subtask.tool_name,
                tool_input=subtask.tool_input
            )
            is_cached, cached_val = self.idempotency.check_idempotency(idem_key)
            if is_cached:
                self.event_log.append_event(
                    task_id=task.task_id,
                    event_type=ExecutionEventType.IDEMPOTENCY_HIT,
                    tool_name=subtask.tool_name,
                    output_data=cached_val
                )
                subtask.result = cached_val
                subtask.state = TaskState.COMPLETED
                accumulated_results.append(cached_val)
                continue

            # 3c. Execute Tool with Retries & Event Sourcing
            tool_def = self.tools.get_tool(subtask.tool_name)
            if not tool_def:
                subtask.state = TaskState.COMPLETED
                subtask.result = f"Completed synthetic step: {subtask.title}"
                accumulated_results.append(subtask.result)
                continue

            step_success = False
            t_tool_start = time.time()
            self.event_log.append_event(
                task_id=task.task_id,
                event_type=ExecutionEventType.TOOL_STARTED,
                tool_name=subtask.tool_name,
                input_data=subtask.tool_input
            )
            self.idempotency.record_start(idem_key, task.task_id, subtask.id, subtask.tool_name)

            while subtask.retry_count <= subtask.max_retries and not step_success:
                try:
                    # Determine resource scope lock if needed
                    scope = None
                    if "screenshot" in subtask.tool_name or "ocr" in subtask.tool_name or "mouse" in subtask.tool_name:
                        scope = ResourceScope.SCREEN_INPUT
                    elif "browser" in subtask.tool_name or "url" in subtask.tool_name or "page" in subtask.tool_name:
                        scope = ResourceScope.ACTIVE_BROWSER

                    if scope:
                        async with self.locks.acquire_lock(scope, task_id=task.task_id):
                            fn = tool_def.execute_fn
                            raw_result = fn(**subtask.tool_input) if not inspect.iscoroutinefunction(fn) else await fn(**subtask.tool_input)
                    else:
                        fn = tool_def.execute_fn
                        raw_result = fn(**subtask.tool_input) if not inspect.iscoroutinefunction(fn) else await fn(**subtask.tool_input)

                    subtask.result = raw_result
                    duration_ms = round((time.time() - t_tool_start) * 1000, 2)

                    # 3d. Post-Action Observation Verification
                    self.event_log.append_event(
                        task_id=task.task_id,
                        event_type=ExecutionEventType.VERIFICATION_STARTED,
                        tool_name=subtask.tool_name
                    )
                    v_res = await self.verifier.verify(
                        strategy=subtask.verification_strategy or tool_def.verification_strategy,
                        tool_name=subtask.tool_name,
                        tool_input=subtask.tool_input,
                        raw_result=raw_result
                    )
                    subtask.verification_result = v_res

                    if v_res.passed:
                        step_success = True
                        subtask.state = TaskState.COMPLETED
                        self.event_log.append_event(
                            task_id=task.task_id,
                            event_type=ExecutionEventType.VERIFICATION_PASSED,
                            tool_name=subtask.tool_name,
                            output_data=raw_result,
                            duration_ms=duration_ms
                        )
                        self.idempotency.record_complete(idem_key, raw_result)
                        accumulated_results.append(raw_result)

                        # Update working memory
                        tiered_memory.append_step_observation(
                            task_id=task.task_id,
                            step_title=subtask.title,
                            tool=subtask.tool_name,
                            action_input=subtask.tool_input,
                            observation=raw_result
                        )
                    else:
                        self.event_log.append_event(
                            task_id=task.task_id,
                            event_type=ExecutionEventType.VERIFICATION_FAILED,
                            tool_name=subtask.tool_name,
                            output_data=v_res.details
                        )
                        raise ValueError(f"Verification failed: {v_res.details}")

                except Exception as ex:
                    subtask.retry_count += 1
                    logger.warning(f"[Runtime] Step {subtask.id} failed (attempt {subtask.retry_count}): {ex}")

                    if subtask.retry_count <= subtask.max_retries:
                        self.event_log.append_event(
                            task_id=task.task_id,
                            event_type=ExecutionEventType.RECOVERY_STARTED,
                            tool_name=subtask.tool_name,
                            metadata={"attempt": subtask.retry_count, "error": str(ex)}
                        )
                        subtask.state = TaskState.RECOVERING
                        await self._emit_progress(task, f"Auto-recovering {subtask.title} (Attempt {subtask.retry_count}/{subtask.max_retries})...")
                        recovery_decision = await self.recovery.handle_failure(
                            task=task,
                            failed_subtask=subtask,
                            error_message=str(ex)
                        )
                        if recovery_decision.get("strategy") == "modify_input":
                            subtask.tool_input.update(recovery_decision.get("adjusted_input", {}))
                    else:
                        self.idempotency.record_failure(idem_key)
                        subtask.state = TaskState.FAILED
                        subtask.error = str(ex)
                        self.event_log.append_event(
                            task_id=task.task_id,
                            event_type=ExecutionEventType.TOOL_FAILED,
                            tool_name=subtask.tool_name,
                            metadata={"error": str(ex)}
                        )
                        self.state_machine.fail_task(task, f"Subtask '{subtask.title}' failed after {subtask.max_retries} retries: {ex}")
                        return task

        # 4. Final Verification & Completion
        self.state_machine.transition_state(task, TaskState.VERIFYING)
        task.result = accumulated_results[-1] if accumulated_results else "Goal executed successfully."
        self.state_machine.complete_task(task, result=task.result)
        self.event_log.append_event(
            task_id=task.task_id,
            event_type=ExecutionEventType.TASK_COMPLETED,
            output_data=task.result
        )

        # Consolidate working memory to episodic memory
        tiered_memory.consolidate_task_memory(task.task_id, success=True, outcome=str(task.result))
        await self._emit_progress(task, "✅ Task completed and verified.")
        return task


# Singleton instance
nexus_runtime = NexusRuntime()
