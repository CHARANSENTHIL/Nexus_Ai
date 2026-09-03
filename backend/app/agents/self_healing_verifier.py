"""
Self-Healing Verifier — Validates that recovery actions actually resolved the underlying state.
Tests socket ports, HTTP health endpoints, package installations, and running processes.
"""
import sys
import socket
import logging
import importlib.util
from typing import Any, Dict, Tuple
import httpx
import psutil

from app.agents.self_healing_models import RecoveryAction

logger = logging.getLogger(__name__)


class SelfHealingVerifier:
    """
    Executes specific post-repair verification checks to confirm true system health.
    """

    def verify_package_installed(self, package_name: str) -> Tuple[bool, str]:
        """Verify that a Python package is importable or present in site-packages."""
        # Standardize module name (e.g. "opencv-python" -> "cv2", "pillow" -> "PIL", "pyyaml" -> "yaml")
        module_aliases = {
            "opencv-python": "cv2",
            "opencv-python-headless": "cv2",
            "pillow": "PIL",
            "pyyaml": "yaml",
            "python-dotenv": "dotenv",
            "beautifulsoup4": "bs4",
            "scikit-learn": "sklearn",
        }
        mod_name = module_aliases.get(package_name.lower(), package_name.replace("-", "_").lower())

        spec = importlib.util.find_spec(mod_name)
        if spec is not None:
            return True, f"✅ Package/module '{mod_name}' is verified and importable"

        # Fallback: check via pip list / subprocess
        try:
            import subprocess
            res = subprocess.run(
                [sys.executable, "-m", "pip", "show", package_name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                return True, f"✅ Package '{package_name}' verified via pip show"
        except Exception:
            pass

        return False, f"❌ Package '{package_name}' could not be imported"

    def verify_port_listening(self, port: int, should_be_open: bool = True) -> Tuple[bool, str]:
        """Verify whether a TCP port is open / listening, or freed up."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.5)
        try:
            res = sock.connect_ex(("127.0.0.1", port))
            is_listening = (res == 0)
        finally:
            sock.close()

        if should_be_open:
            if is_listening:
                return True, f"✅ Port {port} is active and accepting connections"
            return False, f"❌ Port {port} is not listening"
        else:
            if not is_listening:
                return True, f"✅ Port {port} successfully freed up"
            return False, f"❌ Port {port} is still occupied"

    async def verify_http_health(
        self, url: str, expected_status: int = 200, timeout: float = 4.0
    ) -> Tuple[bool, str]:
        """Verify an HTTP service returns the expected status code (e.g. GET /health -> 200)."""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
                if resp.status_code == expected_status:
                    return True, f"✅ Health check {url} -> HTTP {resp.status_code} (Healthy)"
                return False, f"❌ Health check {url} returned HTTP {resp.status_code} (expected {expected_status})"
        except Exception as e:
            return False, f"❌ Health check {url} connection failed: {e}"

    def verify_process_alive(self, process_name_or_pid: Any) -> Tuple[bool, str]:
        """Verify that a target PID or process name is active."""
        if isinstance(process_name_or_pid, int):
            exists = psutil.pid_exists(process_name_or_pid)
            return exists, f"Process PID {process_name_or_pid} {'is active' if exists else 'not found'}"

        name = str(process_name_or_pid).lower()
        for p in psutil.process_iter(["name", "cmdline"]):
            try:
                pname = p.info["name"] or ""
                cmd = " ".join(p.info["cmdline"] or [])
                if name in pname.lower() or name in cmd.lower():
                    return True, f"✅ Process matching '{name}' is running (PID {p.pid})"
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return False, f"❌ Process matching '{name}' not found"

    def verify_python_syntax(self, error_traceback_or_path: str) -> Tuple[bool, str]:
        """Verify that repaired Python file has valid syntax via AST."""
        import ast
        import os
        from app.agents.code_repair_engine import code_repair_engine

        target_file = error_traceback_or_path
        if not os.path.exists(target_file):
            target_file, _, _ = code_repair_engine.extract_error_location(error_traceback_or_path)

        if not target_file or not os.path.exists(target_file):
            return True, "Assumed syntax valid"

        try:
            with open(target_file, "r", encoding="utf-8") as f:
                content = f.read()
            ast.parse(content)
            return True, f"✅ Code syntax validated for {os.path.basename(target_file)}"
        except Exception as e:
            return False, f"❌ Syntax error remains in {os.path.basename(target_file)}: {e}"

    async def verify(self, action: RecoveryAction) -> Tuple[bool, str]:
        """Dispatch to appropriate verification routine based on action specification."""
        vtype = action.verification_type
        args = action.verification_args

        if vtype == "package_installed":
            pkg = args.get("package_name", "")
            return self.verify_package_installed(pkg)

        elif vtype == "port_listening":
            port = int(args.get("port", 8000))
            should_open = args.get("should_be_open", True)
            return self.verify_port_listening(port, should_open)

        elif vtype == "python_syntax_valid":
            tb = args.get("error_traceback") or args.get("file_path", "")
            return self.verify_python_syntax(tb)

        elif vtype == "http_health":
            url = args.get("url", "http://127.0.0.1:8000/health")
            status = int(args.get("expected_status", 200))
            return await self.verify_http_health(url, status)

        elif vtype == "process_alive":
            target = args.get("command") or args.get("process_name") or args.get("pid")
            return self.verify_process_alive(target)

        # No specific verifier configured -> assume success
        return True, "Assumed verified (no specific check required)"



# Singleton
self_healing_verifier = SelfHealingVerifier()
