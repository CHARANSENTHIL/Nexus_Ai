"""
Error Analyzer — Deterministic regex parsing + LLM fallback diagnosis.
Classifies execution errors into categorized ErrorDiagnosis objects.
"""
import re
import json
import logging
from typing import Optional
import httpx

from app.agents.self_healing_models import ErrorCategory, ErrorDiagnosis

logger = logging.getLogger(__name__)


# ── Deterministic Regex Rules (0ms latency, 99% accuracy for known errors) ────
_REGEX_RULES = [
    # 1. Dependency: ModuleNotFoundError / ImportError
    (
        r"(?:ModuleNotFoundError:\s*No module named ['\"]([^'\"]+)['\"]|"
        r"ImportError:\s*cannot import name ['\"]([^'\"]+)['\"]|"
        r"No module named\s+([a-zA-Z0-9_\.-]+))",
        ErrorCategory.DEPENDENCY_ERROR,
        "Missing or unimported Python module",
        0.98,
    ),
    # 2. Dependency: npm / node package missing
    (
        r"(?:Cannot find module ['\"]([^'\"]+)['\"]|npm ERR! missing: ([a-zA-Z0-9_\.-]+))",
        ErrorCategory.DEPENDENCY_ERROR,
        "Missing Node.js package",
        0.95,
    ),
    # 3. Port Conflict
    (
        r"(?:Address already in use|\[WinError 10048\]|EADDRINUSE|bind:\s*address already in use|port\s+(\d+))",
        ErrorCategory.PORT_CONFLICT,
        "Network port already bound by another process",
        0.96,
    ),

    # 4. File Not Found
    (
        r"(?:FileNotFoundError:\s*\[Errno 2\]\s*No such file or directory:\s*['\"]([^'\"]+)['\"]|"
        r"The system cannot find the file specified:?\s*['\"]?([^'\"\n]+)?['\"]?|"
        r"cannot find the path specified)",
        ErrorCategory.FILE_ERROR,
        "Referenced file or directory does not exist on disk",
        0.95,
    ),
    # 5. Permission Error
    (
        r"(?:PermissionError:\s*\[WinError 5\]\s*Access is denied|"
        r"Permission denied|"
        r"Access is denied)",
        ErrorCategory.PERMISSION_ERROR,
        "File or system operation rejected due to insufficient privileges",
        0.95,
    ),
    # 6. Network Error
    (
        r"(?:ConnectionRefusedError|ConnectTimeout|ReadTimeout|"
        r"Failed to establish a new connection|Max retries exceeded with url|"
        r"getaddrinfo failed|ERR_CONNECTION_REFUSED)",
        ErrorCategory.NETWORK_ERROR,
        "Network connection failed, refused, or timed out",
        0.92,
    ),
    # 7. Syntax / Logic / Runtime Error
    (
        r"(?:SyntaxError:\s*([^\n]+)|IndentationError:\s*([^\n]+)|TypeError:\s*([^\n]+)|"
        r"AttributeError:\s*([^\n]+)|NameError:\s*([^\n]+)|ValueError:\s*([^\n]+)|"
        r"IndexError:\s*([^\n]+)|KeyError:\s*([^\n]+)|EOFError:\s*([^\n]+)|UnboundLocalError:\s*([^\n]+))",
        ErrorCategory.SYNTAX_LOGIC_ERROR,
        "Code execution raised runtime error",
        0.92,
    ),

    # 8. Command not recognized / executable missing
    (
        r"(?:'([^']+)' is not recognized as an internal or external command|command not found:\s*(\S+))",
        ErrorCategory.DEPENDENCY_ERROR,
        "Required command line tool or executable is not installed on PATH",
        0.94,
    ),
]


class ErrorAnalyzer:
    """
    Analyzes command output / exceptions using fast deterministic rules first,
    falling back to local LLM diagnosis if the error signature is novel.
    """

    def analyze_deterministic(
        self, stderr: str, stdout: str = "", exit_code: Optional[int] = None
    ) -> Optional[ErrorDiagnosis]:
        """Attempt to classify error using deterministic regex rules (fast, 0ms)."""
        combined = f"{stderr}\n{stdout}".strip()
        if not combined:
            if exit_code is not None and exit_code != 0:
                return ErrorDiagnosis(
                    category=ErrorCategory.APPLICATION_CRASH,
                    root_cause=f"Process exited abnormally with code {exit_code}",
                    confidence=0.80,
                    raw_stderr=stderr,
                    exit_code=exit_code,
                    diagnosed_by="deterministic_parser",
                )
            return None

        for pattern, category, cause_desc, conf in _REGEX_RULES:
            m = re.search(pattern, combined, re.IGNORECASE)
            if m:
                # Find first non-None capture group as missing entity
                entity = next((g for g in m.groups() if g is not None), None)
                if entity:
                    entity = entity.strip().strip("'").strip('"')

                # Port number extraction helper
                if category == ErrorCategory.PORT_CONFLICT:
                    all_nums = re.findall(r"\b(\d{2,5})\b", combined)
                    valid_ports = [n for n in all_nums if n != "10048" and 80 <= int(n) <= 65535]
                    entity = valid_ports[0] if valid_ports else (entity if entity and entity != "10048" else "8000")


                logger.info(f"[ErrorAnalyzer] Deterministic match: {category.value} -> entity '{entity}' ({conf:.2f})")
                return ErrorDiagnosis(
                    category=category,
                    root_cause=f"{cause_desc}{f' ({entity})' if entity else ''}",
                    missing_entity=entity,
                    confidence=conf,
                    raw_stderr=stderr[:1000],
                    exit_code=exit_code,
                    diagnosed_by="deterministic_parser",
                )

        return None

    async def analyze_llm(
        self, stderr: str, stdout: str = "", exit_code: Optional[int] = None
    ) -> ErrorDiagnosis:
        """Fallback to local Ollama LLM to reason about novel or complex errors."""
        combined = (f"STDERR:\n{stderr[:1500]}\n\nSTDOUT:\n{stdout[:500]}").strip()
        prompt = (
            "You are an expert system error diagnostics engine. Analyze the following execution failure output:\n\n"
            f"{combined}\n\n"
            "Identify the category (one of: dependency_error, port_conflict, application_crash, network_error, "
            "file_error, permission_error, syntax_logic_error, unknown), the root cause, and the missing package/port/file entity if any.\n"
            "Return ONLY valid JSON with this format:\n"
            '{"category": "dependency_error", "root_cause": "brief explanation", "missing_entity": "package_or_file_name_or_null", "confidence": 0.85}'
        )

        models_to_try = ["phi4-mini:latest", "qwen3:1.7b", "qwen3:4b", "llama3:latest"]
        for model in models_to_try:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        "http://localhost:11434/api/chat",
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": prompt}],
                            "stream": False,
                            "options": {"temperature": 0.1},
                        },
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        content = data.get("message", {}).get("content", "").strip()
                        # Extract JSON block
                        m = re.search(r"\{.*\}", content, re.DOTALL)
                        if m:
                            parsed = json.loads(m.group(0))
                            cat_str = parsed.get("category", "unknown").lower()
                            try:
                                cat = ErrorCategory(cat_str)
                            except ValueError:
                                cat = ErrorCategory.UNKNOWN

                            logger.info(f"[ErrorAnalyzer] LLM diagnosis ({model}): {cat.value} -> {parsed.get('root_cause')}")
                            return ErrorDiagnosis(
                                category=cat,
                                root_cause=parsed.get("root_cause", "Unclassified execution failure"),
                                missing_entity=parsed.get("missing_entity"),
                                confidence=float(parsed.get("confidence", 0.75)),
                                raw_stderr=stderr[:1000],
                                exit_code=exit_code,
                                diagnosed_by=f"llm_{model}",
                            )
            except Exception as e:
                logger.warning(f"[ErrorAnalyzer] LLM diagnosis error with {model}: {e}")
                continue

        # Default fallback if all models unavailable
        return ErrorDiagnosis(
            category=ErrorCategory.UNKNOWN,
            root_cause="Execution failed with unparsed error",
            confidence=0.50,
            raw_stderr=stderr[:1000],
            exit_code=exit_code,
            diagnosed_by="fallback",
        )

    async def analyze(
        self, stderr: str, stdout: str = "", exit_code: Optional[int] = None
    ) -> ErrorDiagnosis:
        """Main entry point: Deterministic first -> LLM reasoning second."""
        diagnosis = self.analyze_deterministic(stderr, stdout, exit_code)
        if diagnosis:
            return diagnosis
        return await self.analyze_llm(stderr, stdout, exit_code)


# Singleton
error_analyzer = ErrorAnalyzer()
