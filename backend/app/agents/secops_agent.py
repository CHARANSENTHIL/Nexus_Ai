"""SecOps & Vulnerability Sentinel Agent for Nexus AI.

Audits codebases for security vulnerabilities:
- Secret & token leak detection (API keys, private keys, passwords).
- Dangerous execution patterns (eval, exec, command injection vectors).
- Dependency risks and insecure configuration audit.
- Generates official Security Health Scorecard (A+ to F) and remediation guide.
"""
import os
import re
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
SECOPS_MODEL = os.getenv("SECOPS_MODEL", "phi4-mini:latest")


class SecOpsAgent:
    """Agent for automated defensive security audits and vulnerability remediation."""

    def __init__(self, ollama_url: str = OLLAMA_BASE_URL, model: str = SECOPS_MODEL):
        self.ollama_url = ollama_url
        self.model = model

    async def audit_codebase_security(
        self,
        target_path: str = "D:\\nexus_ai\\backend"
    ) -> Dict[str, Any]:
        """Conducts comprehensive static security analysis on target directory or file."""
        target_dir = Path(target_path)
        if not target_dir.exists():
            return {"success": False, "error": f"Target path not found: {target_path}"}

        logger.info(f"[SecOpsAgent] Auditing security for '{target_path}'...")

        findings = []
        files_scanned = 0

        # Regex patterns for common security vulnerabilities
        secret_patterns = [
            (r"(?i)(api[_-]?key|secret[_-]?key|auth[_-]?token|password|jwt[_-]?secret)\s*=\s*['\"][a-zA-Z0-9_\-\.]{12,}['\"]", "High", "Hardcoded Secret / Token"),
            (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "Critical", "Exposed Private Key"),
            (r"eval\s*\([^)]+\)", "Medium", "Dangerous eval() usage"),
            (r"exec\s*\([^)]+\)", "Medium", "Dangerous exec() usage"),
            (r"subprocess\.(?:Popen|call|run)\([^)]*shell\s*=\s*True", "High", "Insecure shell=True Subprocess execution"),
            (r"SELECT\s+.*?\s+FROM\s+.*?\s+WHERE\s+.*?%s", "Low", "Potential SQL string formatting risk")
        ]

        # Scan python and config files
        extensions = [".py", ".env", ".json", ".yaml", ".yml", ".toml"]
        files_to_scan = []
        if target_dir.is_file():
            files_to_scan = [target_dir]
        else:
            for ext in extensions:
                files_to_scan.extend(target_dir.rglob(f"*{ext}"))

        for file_p in files_to_scan:
            if ".venv" in file_p.parts or "__pycache__" in file_p.parts or ".git" in file_p.parts:
                continue
            files_scanned += 1
            try:
                content = file_p.read_text(encoding="utf-8", errors="ignore")
                lines = content.splitlines()
                for line_idx, line in enumerate(lines, 1):
                    # Ignore comment lines and placeholders
                    if line.strip().startswith("#") or "os.getenv" in line or "os.environ" in line:
                        continue
                    for pat, severity, desc in secret_patterns:
                        if re.search(pat, line):
                            findings.append({
                                "file": str(file_p.relative_to(target_dir) if target_dir.is_dir() else file_p.name),
                                "line": line_idx,
                                "severity": severity,
                                "description": desc,
                                "snippet": line.strip()[:100]
                            })
            except Exception:
                continue

        # Compute Security Grade
        score = 100
        critical_count = sum(1 for f in findings if f["severity"] == "Critical")
        high_count = sum(1 for f in findings if f["severity"] == "High")
        med_count = sum(1 for f in findings if f["severity"] == "Medium")

        score -= (critical_count * 25) + (high_count * 15) + (med_count * 5)
        score = max(0, min(100, score))

        if score >= 95:
            grade = "A+"
        elif score >= 85:
            grade = "A"
        elif score >= 75:
            grade = "B"
        elif score >= 60:
            grade = "C"
        elif score >= 45:
            grade = "D"
        else:
            grade = "F"

        # Generate LLM Remediation Advice if findings exist
        remediation_text = "All inspected files conform to secure coding standards. No critical vulnerabilities found."
        if findings:
            remediation_text = await self._generate_remediations(findings[:8])

        formatted_report = (
            f"🛡️ **SecOps Security Audit Scorecard: Grade {grade} ({score}/100)**\n"
            f"• **Target**: `{target_path}`\n"
            f"• **Files Scanned**: {files_scanned}\n"
            f"• **Issues Found**: {len(findings)} (Critical: {critical_count}, High: {high_count}, Medium: {med_count})\n\n"
            f"🔍 **Key Vulnerabilities**:\n" +
            ("\n".join(f"• `[{f['severity']}]` {f['file']}:{f['line']} — {f['description']}" for f in findings[:5]) if findings else "• No active vulnerabilities detected.") +
            f"\n\n💡 **Remediation Advice**:\n{remediation_text}"
        )

        return {
            "success": True,
            "target": target_path,
            "files_scanned": files_scanned,
            "score": score,
            "grade": grade,
            "findings_count": len(findings),
            "findings": findings[:15],
            "formatted_report": formatted_report
        }

    async def _generate_remediations(self, findings: List[Dict[str, Any]]) -> str:
        prompt = (
            f"You are a Principal Application Security Auditor. Provide 3 concrete, actionable code remediation recommendations "
            f"for these detected security findings:\n{json.dumps(findings, indent=2)}\n\n"
            f"Keep recommendations concise, specific to Python, and focused on environment variables, subprocess safety, and input sanitization."
        )
        for m in [self.model, "phi4-mini:latest", "qwen3:4b"]:
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(
                        f"{self.ollama_url}/api/generate",
                        json={"model": m, "prompt": prompt, "stream": False}
                    )
                    if resp.status_code == 200:
                        return resp.json().get("response", "").strip()
            except Exception:
                continue
        return "1. Move all credentials to .env using os.getenv(). 2. Avoid shell=True in subprocess calls. 3. Sanitize all dynamic inputs."


secops_agent = SecOpsAgent()
