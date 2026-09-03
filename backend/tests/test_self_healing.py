"""
Unit and Integration Tests for the Nexus AI Self-Healing Agent Framework.
"""
import os
import sys
import asyncio
import pytest

from app.agents.self_healing_models import (
    ErrorCategory,
    RiskLevel,
    ErrorDiagnosis,
    RecoveryAction,
)
from app.agents.error_analyzer import error_analyzer
from app.agents.recovery_planner import recovery_planner
from app.approval.security_policy import security_policy_engine
from app.agents.self_healing_verifier import self_healing_verifier
from app.agents.self_healing_pipeline import self_healing_pipeline


# ── 1. Error Analyzer Tests ───────────────────────────────────────────────────
class TestErrorAnalyzer:
    def test_module_not_found_error(self):
        stderr = "Traceback (most recent call last):\nModuleNotFoundError: No module named 'fastapi'"
        diag = error_analyzer.analyze_deterministic(stderr)
        assert diag is not None
        assert diag.category == ErrorCategory.DEPENDENCY_ERROR
        assert diag.missing_entity == "fastapi"
        assert diag.confidence >= 0.95

    def test_import_error(self):
        stderr = "ImportError: cannot import name 'BaseModel' from 'pydantic'"
        diag = error_analyzer.analyze_deterministic(stderr)
        assert diag is not None
        assert diag.category == ErrorCategory.DEPENDENCY_ERROR
        assert diag.missing_entity == "BaseModel"

    def test_port_conflict_error(self):
        stderr = "OSError: [WinError 10048] Only one usage of each socket address is normally permitted: ('0.0.0.0', 8000)"
        diag = error_analyzer.analyze_deterministic(stderr)
        assert diag is not None
        assert diag.category == ErrorCategory.PORT_CONFLICT
        assert diag.missing_entity == "8000"

    def test_file_not_found_error(self):
        stderr = "FileNotFoundError: [Errno 2] No such file or directory: 'D:\\Projects\\app.py'"
        diag = error_analyzer.analyze_deterministic(stderr)
        assert diag is not None
        assert diag.category == ErrorCategory.FILE_ERROR
        assert "app.py" in diag.missing_entity

    def test_permission_error(self):
        stderr = "PermissionError: [WinError 5] Access is denied: 'C:\\Windows\\system32\\drivers'"
        diag = error_analyzer.analyze_deterministic(stderr)
        assert diag is not None
        assert diag.category == ErrorCategory.PERMISSION_ERROR

    def test_network_timeout_error(self):
        stderr = "httpx.ConnectTimeout: timed out waiting for connection"
        diag = error_analyzer.analyze_deterministic(stderr)
        assert diag is not None
        assert diag.category == ErrorCategory.NETWORK_ERROR

    def test_syntax_error(self):
        stderr = "SyntaxError: invalid syntax"
        diag = error_analyzer.analyze_deterministic(stderr)
        assert diag is not None
        assert diag.category == ErrorCategory.SYNTAX_LOGIC_ERROR


# ── 2. Recovery Planner Tests ─────────────────────────────────────────────────
class TestRecoveryPlanner:
    def test_plan_dependency_recovery(self):
        diag = ErrorDiagnosis(
            category=ErrorCategory.DEPENDENCY_ERROR,
            root_cause="Missing package",
            missing_entity="fastapi",
        )
        actions = recovery_planner.plan_dependency_recovery(diag)
        assert len(actions) >= 1
        assert actions[0].tool_name == "run_shell_command"
        assert "pip install fastapi" in actions[0].arguments["command"]
        assert actions[0].verification_type == "package_installed"
        assert actions[0].risk_level == RiskLevel.LOW

    def test_plan_port_conflict_recovery(self):
        diag = ErrorDiagnosis(
            category=ErrorCategory.PORT_CONFLICT,
            root_cause="Port occupied",
            missing_entity="8000",
        )
        actions = recovery_planner.plan_port_conflict_recovery(diag)
        assert len(actions) >= 1
        assert actions[0].risk_level == RiskLevel.MEDIUM

    def test_plan_network_exponential_backoff(self):
        diag = ErrorDiagnosis(
            category=ErrorCategory.NETWORK_ERROR,
            root_cause="Timeout",
        )
        actions = recovery_planner.plan_network_recovery(diag, attempt=3)
        assert len(actions) == 1
        assert actions[0].arguments["seconds"] == 8  # 2^3 = 8s


# ── 3. Security Policy Engine Tests ───────────────────────────────────────────
class TestSecurityPolicyEngine:
    def test_pip_install_is_low_risk(self):
        action = RecoveryAction(
            strategy_name="pip_install",
            tool_name="run_shell_command",
            arguments={"command": f'"{sys.executable}" -m pip install pydantic'},
            risk_level=RiskLevel.LOW,
        )
        risk, reason = security_policy_engine.evaluate_risk(action)
        assert risk == RiskLevel.LOW

    def test_powershell_set_mppreference_is_blocked(self):
        action = RecoveryAction(
            strategy_name="disable_defender",
            tool_name="run_shell_command",
            arguments={"command": "powershell Set-MpPreference -DisableRealtimeMonitoring $true"},
            risk_level=RiskLevel.LOW,  # intentionally spoofed low
        )
        risk, reason = security_policy_engine.evaluate_risk(action)
        assert risk == RiskLevel.CRITICAL
        allowed, auth_reason = asyncio.run(security_policy_engine.authorize(action))
        assert allowed is False
        assert "blocked" in auth_reason.lower()

    def test_delete_root_is_high_risk(self):
        action = RecoveryAction(
            strategy_name="clean_files",
            tool_name="run_shell_command",
            arguments={"command": "del /f /s /q D:\\temp\\junk.tmp"},
            risk_level=RiskLevel.LOW,
        )
        risk, reason = security_policy_engine.evaluate_risk(action)
        assert risk == RiskLevel.HIGH


# ── 4. Self-Healing Verifier Tests ─────────────────────────────────────────────
class TestSelfHealingVerifier:
    def test_verify_installed_package(self):
        # pytest and json are definitely installed in the venv
        ok, msg = self_healing_verifier.verify_package_installed("pytest")
        assert ok is True
        assert "verified" in msg.lower() or "importable" in msg.lower()

    def test_verify_missing_package(self):
        ok, msg = self_healing_verifier.verify_package_installed("non_existent_fake_package_xyz_999")
        assert ok is False

    def test_verify_running_process_by_pid(self):
        current_pid = os.getpid()
        ok, msg = self_healing_verifier.verify_process_alive(current_pid)
        assert ok is True

    def test_verify_action_dispatcher(self):
        action = RecoveryAction(
            strategy_name="install",
            tool_name="run_shell_command",
            verification_type="package_installed",
            verification_args={"package_name": "pydantic"},
        )
        ok, msg = asyncio.run(self_healing_verifier.verify(action))
        assert ok is True


# ── 5. End-to-End Self-Healing Pipeline Tests ─────────────────────────────────
class TestSelfHealingPipeline:
    def test_successful_command_no_healing_needed(self):
        res = asyncio.run(
            self_healing_pipeline.run(
                command=f'"{sys.executable}" -c "print(\'Hello Nexus Self-Healing\')"',
                max_retries=1,
            )
        )
        assert res["success"] is True
        assert res["attempts"] == 1
        assert "Hello Nexus" in res["output"]
        assert len(res["repairs_performed"]) == 0

    def test_project_execution_detection(self, tmp_path):
        from app.agents.planner import IntentRouter, _resolve_project_target
        proj_dir = tmp_path / "MyProject"
        proj_dir.mkdir()
        script = proj_dir / "calculator.py"
        script.write_text("print('calc')\n")

        resolved = _resolve_project_target(str(proj_dir))
        assert resolved is not None
        assert "calculator.py" in resolved["command"]

        tasks = IntentRouter.detect(f"run the project {proj_dir}")
        assert tasks is not None
        assert len(tasks) == 1
        assert tasks[0]["tool"] == "run_shell_command"
        assert "calculator.py" in tasks[0]["tool_input"]["command"]


    def test_code_repair_engine_heuristic_name_error(self, tmp_path):
        from app.agents.code_repair_engine import code_repair_engine
        buggy_code = "def calc(x):\n    a = 10\n    return a + bvdfsdsda\n"
        test_file = tmp_path / "buggy.py"
        test_file.write_text(buggy_code)

        tb = f'File "{test_file}", line 3, in calc\n    return a + bvdfsdsda\nNameError: name \'bvdfsdsda\' is not defined'
        res = asyncio.run(code_repair_engine.repair_file(tb))
        assert res["success"] is True
        fixed_content = test_file.read_text()
        assert "return a + a" in fixed_content or "return a +" in fixed_content

    def test_code_repair_function_call_name_error(self, tmp_path):
        from app.agents.code_repair_engine import code_repair_engine
        buggy_code = "def factorial(n):\n    return 1\n\nif __name__ == '__main__':\n    print(f'raw(5) = {raw(5)}')\n"
        test_file = tmp_path / "fact.py"
        test_file.write_text(buggy_code)

        tb = f'File "{test_file}", line 5, in <module>\n    print(f\'raw(5) = {{raw(5)}}\')\nNameError: name \'raw\' is not defined'
        res = asyncio.run(code_repair_engine.repair_file(tb))
        assert res["success"] is True
        fixed_content = test_file.read_text()
        assert "factorial(5)" in fixed_content

    def test_code_repair_missing_colon(self, tmp_path):
        from app.agents.code_repair_engine import code_repair_engine
        buggy_code = "def test_fn(x)\n    return x * 2\n"
        test_file = tmp_path / "syntax.py"
        test_file.write_text(buggy_code)

        tb = f'File "{test_file}", line 1\n    def test_fn(x)\n                  ^\nSyntaxError: expected \':\''
        res = asyncio.run(code_repair_engine.repair_file(tb))
        assert res["success"] is True
        fixed_content = test_file.read_text()
        assert "def test_fn(x):" in fixed_content



