"""
Self-Healing Pipeline — Central orchestrator executing the Observe → Analyze → Plan → Security → Repair → Verify → Retry lifecycle.
"""
import time
import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from app.agents.self_healing_models import (
    ErrorDiagnosis,
    RecoveryAction,
    RepairOutcome,
)
from app.agents.error_analyzer import error_analyzer
from app.agents.recovery_planner import recovery_planner
from app.approval.security_policy import security_policy_engine
from app.agents.self_healing_verifier import self_healing_verifier
from app.agents.tools.app_tools import run_shell_command

logger = logging.getLogger(__name__)


class SelfHealingPipeline:
    """
    Executes tasks wrapped in an autonomous, security-bounded self-healing lifecycle.
    """

    async def _execute_command(self, cmd: str) -> Dict[str, Any]:
        """Run a shell command asynchronously and return exit_code, stdout, and stderr."""
        try:
            fn = getattr(run_shell_command, "func", run_shell_command)
            res = await asyncio.to_thread(fn, command=cmd)
            if isinstance(res, dict):
                exit_code = 0 if res.get("success", False) else (res.get("returncode") or 1)
                stdout = res.get("stdout", "") or res.get("output", "") or res.get("message", "")
                stderr = res.get("stderr", "") or res.get("error", "") if exit_code != 0 else ""
                return {"exit_code": exit_code, "stdout": stdout, "stderr": stderr}

            return {"exit_code": 0, "stdout": str(res), "stderr": ""}
        except Exception as e:
            return {"exit_code": 1, "stdout": "", "stderr": str(e)}

    async def _execute_action(self, action: RecoveryAction) -> Dict[str, Any]:
        """Execute a specific remediation action tool."""
        tool = action.tool_name
        args = action.arguments

        if tool == "run_shell_command":
            cmd = args.get("command", "")
            return await self._execute_command(cmd)

        elif tool == "kill_process":
            from app.agents.tools.system_tools import kill_process
            fn = getattr(kill_process, "func", kill_process)
            res = await asyncio.to_thread(fn, pid=args.get("pid", 0), process_name=args.get("process_name", ""))
            return {"exit_code": 0 if res.get("success", True) else 1, "stdout": res.get("message", ""), "stderr": ""}

        elif tool == "repair_source_code":
            from app.agents.code_repair_engine import code_repair_engine
            tb = args.get("error_traceback", "")
            target_file = args.get("file_path")
            res = await code_repair_engine.repair_file(tb, target_file)
            if res.get("success", False):
                return {
                    "exit_code": 0,
                    "stdout": res.get("explanation", "Code repaired successfully"),
                    "stderr": "",
                }
            return {"exit_code": 1, "stdout": "", "stderr": res.get("error", "Code repair failed")}

        elif tool == "sleep":
            sec = args.get("seconds", 2.0)
            await asyncio.sleep(sec)
            return {"exit_code": 0, "stdout": f"Slept {sec}s", "stderr": ""}

        return {"exit_code": 0, "stdout": f"Executed tool {tool}", "stderr": ""}


    async def run(
        self,
        command: str,
        goal: str = "",
        user_id: str = "default_user",
        project_dir: str = "",
        max_retries: int = 3,
        notify_fn: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        Execute command with full self-healing capabilities:
        Execute -> Observe -> Analyze -> Plan -> Authorize -> Repair -> Verify -> Retry
        """
        t0 = time.perf_counter()
        repairs_performed: List[Dict[str, Any]] = []

        for attempt in range(1, max_retries + 2):
            logger.info(f"[SelfHealing] ▶ Execution attempt {attempt}/{max_retries + 1}: '{command[:60]}'")
            res = await self._execute_command(command)

            # Check if execution succeeded
            if res["exit_code"] == 0 and not res.get("stderr"):
                total_latency = int((time.perf_counter() - t0) * 1000)
                logger.info(f"[SelfHealing] ✅ Task succeeded on attempt {attempt} ({total_latency}ms)")
                return {
                    "success": True,
                    "output": res["stdout"],
                    "attempts": attempt,
                    "repairs_performed": repairs_performed,
                    "latency_ms": total_latency,
                }

            # If failed and retries exhausted
            if attempt > max_retries:
                logger.error(f"[SelfHealing] ❌ Max retries ({max_retries}) exhausted for '{command[:60]}'")
                break

            # ── 1. Error Analyzer ───────────────────────────────────────────────
            stderr = res.get("stderr", "") or res.get("stdout", "")
            diagnosis = await error_analyzer.analyze(stderr, res.get("stdout", ""), res.get("exit_code"))
            logger.info(f"[SelfHealing] 🔍 Diagnosis: {diagnosis.category.value} -> {diagnosis.root_cause} (conf: {diagnosis.confidence:.2f})")

            # ── 2. Recovery Planner ─────────────────────────────────────────────
            proposed_actions = recovery_planner.plan(
                diagnosis=diagnosis,
                project_dir=project_dir,
                original_command=command,
                user_id=user_id,
                attempt=attempt,
            )

            if not proposed_actions:
                logger.warning("[SelfHealing] No recovery strategies available for this error")
                await asyncio.sleep(1.5)
                continue

            # ── 3. Security Check, Execution, and Verification ─────────────────
            repair_successful = False
            for action in proposed_actions:
                logger.info(f"[SelfHealing] 🛡️ Evaluating recovery action: {action.description}")

                # Security authorization check
                allowed, auth_reason = await security_policy_engine.authorize(action, user_id, notify_fn)
                if not allowed:
                    logger.warning(f"[SelfHealing] 🚫 Recovery action '{action.description}' rejected by policy: {auth_reason}")
                    continue

                # Execute repair action
                repair_res = await self._execute_action(action)
                await asyncio.sleep(1.0)  # Settle state

                # Verify repair
                v_passed, v_detail = await self_healing_verifier.verify(action)
                logger.info(f"[SelfHealing] 🔬 Repair verification: passed={v_passed} | {v_detail}")

                repairs_performed.append({
                    "attempt": attempt,
                    "diagnosis": diagnosis.model_dump(),
                    "action": action.description,
                    "verification": v_detail,
                    "passed": v_passed,
                })

                if v_passed:
                    repair_successful = True
                    # Record into ChromaDB experience memory
                    project_name = project_dir or "default_project"
                    recovery_planner.store_repair_experience(user_id, project_name, diagnosis, action)
                    logger.info(f"[SelfHealing] ✅ Repair '{action.description}' verified! Retrying original command...")
                    break

            if not repair_successful:
                logger.warning(f"[SelfHealing] Repair actions for attempt {attempt} did not pass verification")
                await asyncio.sleep(2.0)

        total_latency = int((time.perf_counter() - t0) * 1000)
        return {
            "success": False,
            "error": res.get("stderr", "Execution failed after all recovery attempts"),
            "output": res.get("stdout", ""),
            "attempts": max_retries + 1,
            "repairs_performed": repairs_performed,
            "latency_ms": total_latency,
        }


# Singleton
self_healing_pipeline = SelfHealingPipeline()
