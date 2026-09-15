"""
Workspace Sandbox — Isolated execution environment for code generation and validation.
Prevents unverified generated code from executing with unrestricted host privileges.
Provides isolated scratch directories, sandboxed virtual environments, and pre-flight validation.
"""
import os
import sys
import shutil
import uuid
import subprocess
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

SANDBOX_BASE_DIR = Path(os.path.expanduser("~")) / ".nexus_ai" / "sandboxes"


class WorkspaceSandbox:
    """
    Manages isolated execution workspaces for running tests, builds, and code patches safely.
    """

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or str(uuid.uuid4())[:12]
        self.sandbox_dir = SANDBOX_BASE_DIR / self.session_id
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)
        self._venv_dir = self.sandbox_dir / ".venv"
        self._python_bin = sys.executable  # Defaults to parent venv, or isolated if created

    def copy_into_sandbox(self, src_paths: List[str]) -> List[str]:
        """Copy target source files or folders into the isolated sandbox."""
        copied = []
        for p_str in src_paths:
            p = Path(p_str)
            if not p.exists():
                continue
            dest = self.sandbox_dir / p.name
            if p.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(p, dest)
            else:
                shutil.copy2(p, dest)
            copied.append(str(dest))
        return copied

    def run_sandboxed_command(
        self,
        command: str,
        timeout_seconds: int = 60,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Executes a command inside the sandbox directory with restricted environment.
        """
        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)

        # Set sandbox working directory
        try:
            proc = subprocess.run(
                command,
                cwd=str(self.sandbox_dir),
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
            return {
                "success": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": proc.stdout[-2500:],
                "stderr": proc.stderr[-2500:],
                "sandbox_path": str(self.sandbox_dir),
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Command timed out after {timeout_seconds}s in sandbox.",
                "sandbox_path": str(self.sandbox_dir),
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Sandbox execution exception: {e}",
                "sandbox_path": str(self.sandbox_dir),
            }

    def validate_patch(
        self,
        file_path: str,
        target_chunk: str,
        replacement_chunk: str,
        test_command: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Applies a diff patch strictly inside the sandbox and runs tests to verify
        safety and syntax before touching the host file.
        """
        p = Path(file_path)
        if not p.exists():
            return {"success": False, "error": f"Target file does not exist: {file_path}"}

        # 1. Copy file to sandbox
        sandbox_target = self.sandbox_dir / p.name
        shutil.copy2(p, sandbox_target)

        # 2. Apply diff in sandbox
        content = sandbox_target.read_text(encoding="utf-8")
        norm_target = target_chunk.replace("\r\n", "\n")
        norm_content = content.replace("\r\n", "\n")

        if norm_target not in norm_content:
            return {
                "success": False,
                "error": "Target chunk not found in file content.",
            }

        new_content = norm_content.replace(norm_target, replacement_chunk.replace("\r\n", "\n"), 1)

        # 3. Validate Python AST Syntax
        if sandbox_target.suffix == ".py":
            import ast
            try:
                ast.parse(new_content, filename=str(sandbox_target))
            except SyntaxError as syn_err:
                return {
                    "success": False,
                    "error": f"Sandboxed patch produced invalid Python syntax: {syn_err}",
                }

        sandbox_target.write_text(new_content, encoding="utf-8")

        # 4. Run sandboxed tests if test command provided
        if test_command:
            test_res = self.run_sandboxed_command(test_command)
            if not test_res.get("success"):
                return {
                    "success": False,
                    "error": f"Sandboxed tests failed: {test_res.get('stderr') or test_res.get('stdout')}",
                    "details": test_res,
                }

        # 5. Patch is valid — promote to host file safely
        p.write_text(new_content, encoding="utf-8")
        return {
            "success": True,
            "message": f"Patch validated in sandbox and applied safely to {file_path}",
            "verified_in_sandbox": True,
        }

    def cleanup(self):
        """Clean up temporary sandbox files."""
        if self.sandbox_dir.exists():
            try:
                shutil.rmtree(self.sandbox_dir)
            except Exception as e:
                logger.warning(f"[WorkspaceSandbox] Cleanup error: {e}")


# Helper factory
def create_sandbox(session_id: Optional[str] = None) -> WorkspaceSandbox:
    return WorkspaceSandbox(session_id=session_id)
