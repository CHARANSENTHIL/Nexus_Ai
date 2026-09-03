"""
Recovery Planner — Multi-strategy remediation planning and ChromaDB experience recall.
Generates prioritized RecoveryAction sequences tailored to ErrorDiagnosis.
"""
import os
import sys
import json
import logging
from typing import Any, Dict, List, Optional
import psutil

from app.agents.self_healing_models import (
    ErrorCategory,
    ErrorDiagnosis,
    RecoveryAction,
    RiskLevel,
)

logger = logging.getLogger(__name__)


class RecoveryPlanner:
    """
    Formulates progressive recovery strategies for categorized errors.
    Integrates ChromaDB to remember and immediately reuse successful past repairs.
    """

    def __init__(self):
        self._memory_store = None

    def _get_memory(self):
        if self._memory_store is None:
            try:
                from app.memory.chroma_store import memory_store
                self._memory_store = memory_store
            except Exception as e:
                logger.warning(f"[RecoveryPlanner] ChromaStore unavailable: {e}")
        return self._memory_store

    # ── 1. Experience Memory (ChromaDB) ─────────────────────────────────────────
    def store_repair_experience(
        self,
        user_id: str,
        project_name: str,
        diagnosis: ErrorDiagnosis,
        action: RecoveryAction,
    ):
        """Record a successful remediation into ChromaDB for future instant recall."""
        mem = self._get_memory()
        if not mem:
            return
        try:
            doc = (
                f"Project: {project_name}\n"
                f"Category: {diagnosis.category.value}\n"
                f"Error: {diagnosis.root_cause}\n"
                f"Entity: {diagnosis.missing_entity}\n"
                f"Fix: {action.strategy_name} -> {action.tool_name}({action.arguments})"
            )
            action_json = json.dumps(action.model_dump())
            mem.store(
                document=doc,
                metadata={
                    "user_id": user_id,
                    "project": project_name,
                    "category": diagnosis.category.value,
                    "missing_entity": diagnosis.missing_entity or "",
                    "action_json": action_json,
                },
                user_id=user_id,
            )
            logger.info(f"[RecoveryPlanner] 🧠 Stored repair experience in ChromaDB for '{diagnosis.root_cause}'")
        except Exception as e:
            logger.warning(f"[RecoveryPlanner] Failed to store repair experience: {e}")

    def recall_repair_experience(
        self, user_id: str, project_name: str, diagnosis: ErrorDiagnosis
    ) -> Optional[RecoveryAction]:
        """Check if we have an existing verified fix for this exact error in ChromaDB."""
        mem = self._get_memory()
        if not mem:
            return None
        try:
            query = f"{project_name} {diagnosis.category.value} {diagnosis.root_cause} {diagnosis.missing_entity}"
            memories = mem.search_memory(
                user_id=user_id,
                project_id="default",
                query=query,
                top_k=1,
            )
            if memories and len(memories) > 0:
                top = memories[0]
                if top.distance < 0.25 and "action_json" in top.metadata:
                    data = json.loads(top.metadata["action_json"])
                    logger.info(f"[RecoveryPlanner] ⚡ Instant ChromaDB Memory Recall ({top.distance:.3f}) for '{diagnosis.root_cause}'")
                    return RecoveryAction(**data)
        except Exception as e:
            logger.warning(f"[RecoveryPlanner] Chroma recall error: {e}")
        return None

    # ── 2. Strategy Generators ──────────────────────────────────────────────────
    def plan_dependency_recovery(
        self, diagnosis: ErrorDiagnosis, project_dir: str = ""
    ) -> List[RecoveryAction]:
        """Generate strategies for missing Python / Node packages."""
        pkg = diagnosis.missing_entity or "required_package"
        venv_python = sys.executable  # active venv python

        actions = []

        # Strategy 1: Direct pip install in active venv
        install_cmd = f'"{venv_python}" -m pip install {pkg}'
        actions.append(
            RecoveryAction(
                strategy_name="pip_install_package",
                tool_name="run_shell_command",
                arguments={"command": install_cmd},
                risk_level=RiskLevel.LOW,
                description=f"Install missing package '{pkg}' via pip",
                verification_type="package_installed",
                verification_args={"package_name": pkg},
            )
        )

        # Strategy 2: If requirements.txt exists in project dir, install full requirements
        req_path = os.path.join(project_dir, "requirements.txt") if project_dir else "requirements.txt"
        actions.append(
            RecoveryAction(
                strategy_name="pip_install_requirements",
                tool_name="run_shell_command",
                arguments={"command": f'"{venv_python}" -m pip install -r "{req_path}"'},
                risk_level=RiskLevel.LOW,
                description="Install all dependencies from requirements.txt",
                verification_type="package_installed",
                verification_args={"package_name": pkg},
            )
        )

        return actions

    def plan_port_conflict_recovery(
        self, diagnosis: ErrorDiagnosis, preferred_port: int = 8000
    ) -> List[RecoveryAction]:
        """Generate strategies for port already in use."""
        port = int(diagnosis.missing_entity) if diagnosis.missing_entity and diagnosis.missing_entity.isdigit() else preferred_port
        actions = []

        # Find PID bound to port
        found_pid = None
        try:
            for conn in psutil.net_connections(kind="inet"):
                if conn.laddr and conn.laddr.port == port and conn.status == "LISTEN":
                    found_pid = conn.pid
                    break
        except Exception:
            pass

        if found_pid:
            actions.append(
                RecoveryAction(
                    strategy_name="terminate_conflicting_port_pid",
                    tool_name="kill_process",
                    arguments={"pid": found_pid},
                    risk_level=RiskLevel.MEDIUM,
                    description=f"Terminate stale process (PID {found_pid}) occupying port {port}",
                    verification_type="port_listening",
                    verification_args={"port": port, "should_be_open": False},
                )
            )

        # Fallback: kill by port via Windows netstat/taskkill
        actions.append(
            RecoveryAction(
                strategy_name="kill_process_on_port_win32",
                tool_name="run_shell_command",
                arguments={
                    "command": f'powershell -Command "Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force }}"'
                },
                risk_level=RiskLevel.MEDIUM,
                description=f"Free up port {port} by stopping conflicting process",
                verification_type="port_listening",
                verification_args={"port": port, "should_be_open": False},
            )
        )

        return actions

    def plan_crash_recovery(
        self, diagnosis: ErrorDiagnosis, command: str = ""
    ) -> List[RecoveryAction]:
        """Generate strategies for crashed subprocesses or applications."""
        actions = []
        if command:
            actions.append(
                RecoveryAction(
                    strategy_name="restart_command",
                    tool_name="run_shell_command",
                    arguments={"command": command},
                    risk_level=RiskLevel.LOW,
                    description=f"Restart crashed command: '{command[:60]}'",
                    verification_type="process_alive",
                    verification_args={"command": command},
                )
            )
        return actions

    def plan_syntax_logic_recovery(
        self, diagnosis: ErrorDiagnosis, raw_stderr: str = ""
    ) -> List[RecoveryAction]:
        """Generate AI code repair action to fix syntax or runtime logic error in source file."""
        return [
            RecoveryAction(
                strategy_name="ai_code_repair",
                tool_name="repair_source_code",
                arguments={"error_traceback": raw_stderr or diagnosis.raw_stderr},
                risk_level=RiskLevel.LOW,
                description=f"Auto-repair source code bug ({diagnosis.missing_entity or diagnosis.root_cause})",
                verification_type="python_syntax_valid",
                verification_args={"error_traceback": raw_stderr or diagnosis.raw_stderr},
            )
        ]

    def plan_network_recovery(
        self, diagnosis: ErrorDiagnosis, attempt: int = 1
    ) -> List[RecoveryAction]:
        """Generate strategies for network timeouts with exponential backoff."""
        delay = min(2 ** attempt, 16)
        return [
            RecoveryAction(
                strategy_name="exponential_backoff_retry",
                tool_name="sleep",
                arguments={"seconds": delay},
                risk_level=RiskLevel.LOW,
                description=f"Wait {delay}s (exponential backoff) and retry network operation",
                verification_type="",
            )
        ]

    # ── Main Entry Point ────────────────────────────────────────────────────────
    def plan(
        self,
        diagnosis: ErrorDiagnosis,
        project_dir: str = "",
        original_command: str = "",
        user_id: str = "default_user",
        attempt: int = 1,
    ) -> List[RecoveryAction]:
        """
        Formulates prioritized recovery actions:
        1. Checks ChromaDB experience memory for known successful fix.
        2. Dispatches to category-specific strategy generator.
        """
        # Step 1: Check ChromaDB memory first
        project_name = os.path.basename(project_dir) if project_dir else "default_project"
        recalled = self.recall_repair_experience(user_id, project_name, diagnosis)
        if recalled:
            return [recalled]

        # Step 2: Categorical strategy generators
        if diagnosis.category == ErrorCategory.DEPENDENCY_ERROR:
            return self.plan_dependency_recovery(diagnosis, project_dir)

        elif diagnosis.category == ErrorCategory.PORT_CONFLICT:
            port = int(diagnosis.missing_entity) if diagnosis.missing_entity and diagnosis.missing_entity.isdigit() else 8000
            return self.plan_port_conflict_recovery(diagnosis, port)

        elif diagnosis.category == ErrorCategory.SYNTAX_LOGIC_ERROR:
            return self.plan_syntax_logic_recovery(diagnosis, diagnosis.raw_stderr)

        elif diagnosis.category == ErrorCategory.APPLICATION_CRASH:
            return self.plan_crash_recovery(diagnosis, original_command)

        elif diagnosis.category == ErrorCategory.NETWORK_ERROR:
            return self.plan_network_recovery(diagnosis, attempt)


        # Default fallback
        return [
            RecoveryAction(
                strategy_name="generic_retry",
                tool_name="sleep",
                arguments={"seconds": 2.0},
                risk_level=RiskLevel.LOW,
                description=f"Retry after settling state for {diagnosis.root_cause}",
                verification_type="",
            )
        ]


# Singleton
recovery_planner = RecoveryPlanner()
