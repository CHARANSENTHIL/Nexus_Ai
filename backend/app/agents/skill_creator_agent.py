"""Self-Evolving Skill & Tool Creator (Meta-Agent) for Nexus AI.

Synthesizes new Python tools on-the-fly using local Ollama (phi4-mini),
validates the code syntax and sandboxed execution,
and hot-reloads the newly created tool into the active Tool Registry.
"""
import ast
import importlib
import inspect
import json
import logging
import os
import re
import sys
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
META_MODEL = os.getenv("META_MODEL", "phi4-mini:latest")
CUSTOM_TOOLS_DIR = Path("D:/nexus_ai/backend/app/agents/tools/custom_tools")
CUSTOM_TOOLS_DIR.mkdir(parents=True, exist_ok=True)


class SkillCreatorAgent:
    """Meta-Agent that writes, validates, and hot-reloads new tools dynamically."""

    def __init__(self, ollama_url: str = OLLAMA_BASE_URL, model: str = META_MODEL):
        self.ollama_url = ollama_url
        self.model = model

    async def create_and_register_tool(
        self,
        tool_name: str,
        purpose: str,
        example_usage: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generates, tests, and hot-reloads a brand new Python tool."""
        clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", tool_name).lower().strip("_")
        if not clean_name:
            clean_name = "custom_dynamic_tool"

        logger.info(f"[SkillCreator] Synthesizing new tool '{clean_name}' for purpose: '{purpose}'...")

        # 1. Generate Python tool code using LLM
        code = await self._generate_tool_code(clean_name, purpose, example_usage)
        if not code:
            return {"success": False, "error": "Failed to synthesize valid Python tool code."}

        # 2. Syntax Validation via AST
        try:
            ast.parse(code)
        except SyntaxError as e:
            logger.error(f"[SkillCreator] Syntax validation failed: {e}")
            # Attempt one repair pass
            code = await self._repair_code(code, str(e))
            try:
                ast.parse(code)
            except SyntaxError as e2:
                return {"success": False, "error": f"Generated tool has syntax error: {e2}"}

        # 3. Save to custom_tools directory
        target_file = CUSTOM_TOOLS_DIR / f"{clean_name}.py"
        target_file.write_text(code, encoding="utf-8")
        logger.info(f"[SkillCreator] Tool written to {target_file}")

        # 4. Dry-run sandboxed execution test
        test_success, test_err = self._test_tool_syntax_and_import(target_file)
        if not test_success:
            return {"success": False, "error": f"Tool import/execution test failed: {test_err}"}

        # 5. Hot-reload into current running Python process and Planner registry
        registered_func = self._hot_reload_tool(clean_name, target_file)
        if not registered_func:
            return {"success": False, "error": "Tool created and saved, but hot-reload into registry failed."}

        return {
            "success": True,
            "tool_name": clean_name,
            "file_path": str(target_file),
            "purpose": purpose,
            "message": f"Tool '{clean_name}' successfully created, verified, and hot-reloaded into active tool registry."
        }

    async def _generate_tool_code(self, name: str, purpose: str, example: Optional[str]) -> str:
        """Prompt local model to produce a self-contained Python tool file with @tool decorator."""
        system_prompt = (
            "You are a Senior Python Meta-Programming Engineer. "
            "Write a single, robust, self-contained Python tool module. "
            "Rules:\n"
            "1. Must use standard Python libraries or popular pre-installed packages.\n"
            "2. Must define a function decorated with @tool from langchain_core.tools import tool.\n"
            "3. Must return a dict with at least {'success': bool, 'message' or 'result': Any}.\n"
            "4. Include comprehensive try/except error handling and descriptive docstring.\n"
            "5. Return ONLY the raw Python code enclosed in ```python ... ``` without conversational commentary."
        )

        user_prompt = (
            f"Tool Name: {name}\n"
            f"Purpose: {purpose}\n"
            f"Example Usage / Inputs: {example or 'Standard parameters'}\n\n"
            "Generate the complete Python module:"
        )

        for m in [self.model, "phi4-mini:latest", "qwen3:4b", "qwen3:1.7b"]:
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        f"{self.ollama_url}/api/generate",
                        json={"model": m, "prompt": f"{system_prompt}\n\n{user_prompt}", "stream": False}
                    )
                    if resp.status_code == 200:
                        raw = resp.json().get("response", "")
                        match = re.search(r"```(?:python)?\s*([\s\S]*?)\s*```", raw)
                        code = match.group(1).strip() if match else raw.strip()
                        if "def " in code:
                            return code
            except Exception as e:
                logger.warning(f"[SkillCreator] LLM {m} failed: {e}")
                continue

        return ""

    async def _repair_code(self, code: str, err: str) -> str:
        """Fix syntax errors in generated code."""
        prompt = f"Fix this Python code syntax error:\nError: {err}\n\nCode:\n```python\n{code}\n```\n\nReturn fixed Python code only in ```python``` block."
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={"model": "phi4-mini:latest", "prompt": prompt, "stream": False}
                )
                if resp.status_code == 200:
                    raw = resp.json().get("response", "")
                    match = re.search(r"```(?:python)?\s*([\s\S]*?)\s*```", raw)
                    return match.group(1).strip() if match else raw.strip()
        except Exception:
            pass
        return code

    def _test_tool_syntax_and_import(self, file_path: Path) -> tuple[bool, str]:
        """Runs a separate Python process to ensure the file imports cleanly without crashing."""
        try:
            res = subprocess.run(
                [sys.executable, "-c", f"import sys; sys.path.insert(0, r'{file_path.parent.parent.parent.parent}'); import importlib.util; spec = importlib.util.spec_from_file_location('mod', r'{file_path}'); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); print('OK')"],
                capture_output=True,
                text=True,
                timeout=15
            )
            if res.returncode == 0 and "OK" in res.stdout:
                return True, ""
            return False, res.stderr or res.stdout
        except Exception as e:
            return False, str(e)

    def _hot_reload_tool(self, name: str, file_path: Path) -> Optional[Any]:
        """Dynamically imports the new tool and inserts it into the Planner tool registry."""
        try:
            spec = importlib.util.spec_from_file_location(f"app.agents.tools.custom_tools.{name}", str(file_path))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[f"app.agents.tools.custom_tools.{name}"] = mod
            spec.loader.exec_module(mod)

            # Find callable tool
            target_func = None
            for attr_name, attr_val in inspect.getmembers(mod):
                if hasattr(attr_val, "func") or (inspect.isfunction(attr_val) and attr_name == name):
                    target_func = attr_val
                    break

            if target_func:
                from app.agents.planner import planner_agent
                func_callable = getattr(target_func, "func", target_func)
                planner_agent.tool_registry[name] = func_callable
                logger.info(f"[SkillCreator] 🚀 Hot-reloaded '{name}' into active planner registry!")
                return func_callable
        except Exception as e:
            logger.error(f"[SkillCreator] Hot-reload error: {e}", exc_info=True)

        return None

    def list_all_custom_tools(self) -> List[Dict[str, str]]:
        """Returns list of all dynamically created tools."""
        tools = []
        for p in CUSTOM_TOOLS_DIR.glob("*.py"):
            if p.name == "__init__.py":
                continue
            tools.append({
                "name": p.stem,
                "file": str(p),
                "modified": os.path.getmtime(p)
            })
        return tools


skill_creator_agent = SkillCreatorAgent()
