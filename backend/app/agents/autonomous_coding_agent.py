"""
Autonomous Coding Agent (Software Engineer) — End-to-end repository modification & debug loop.
Workflow:
  Goal -> AST Indexing -> Targeted Code Retrieval -> Diagnosis -> Patch (AST Validated) -> Test Execution -> Verify.
"""
import os
import re
import sys
import json
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional

from langchain_ollama import OllamaLLM
from langchain_core.prompts import PromptTemplate

from app.config import settings
from app.agents.codebase_intelligence import codebase_intelligence
from app.agents.tools.coding_tools import (
    search_codebase_symbols,
    get_file_symbol_outline,
    get_symbol_implementation,
    apply_targeted_diff,
    run_unit_tests,
    manage_dev_server,
)

logger = logging.getLogger(__name__)

CODING_AGENT_ROLE = (
    "an Autonomous Software Engineer. You diagnose software issues, search codebase symbols "
    "using AST trees, apply targeted bug fixes, run pytest/unit tests, and ensure full verification."
)

coding_agent_tools = [
    search_codebase_symbols,
    get_file_symbol_outline,
    get_symbol_implementation,
    apply_targeted_diff,
    run_unit_tests,
    manage_dev_server,
]

PATCH_PROMPT = PromptTemplate(
    input_variables=["goal", "symbol_name", "file_path", "current_code", "error_log"],
    template="""You are an expert Autonomous Software Engineer.
Your task is to fix an issue or implement a requested feature in the codebase.

Goal: {goal}
File: {file_path}
Symbol: {symbol_name}

Current Implementation:
```python
{current_code}
```

Error Log / Context:
{error_log}

Output ONLY valid JSON with this exact structure:
{{
  "analysis": "Brief diagnosis of the issue",
  "target_chunk": "Exact lines of code from Current Implementation that need to be replaced",
  "replacement_chunk": "The new replacement lines of code",
  "explanation": "Why this fix resolves the problem"
}}
Do NOT wrap your JSON in any conversational text or markdown other than the raw JSON object.
"""
)


class AutonomousCodingAgent:
    """Autonomous software engineering agent with closed-loop debugging and test-driven fixes."""

    def __init__(self, root_dir: str = "D:\\nexus_ai\\backend"):
        self.root_dir = root_dir
        self.codebase = codebase_intelligence

    def _get_llm(self):
        url = settings.get_ollama_url()
        model_name = getattr(settings, "OLLAMA_COMPLEX_MODEL", "qwen3:4b")
        return OllamaLLM(model=model_name, base_url=url, temperature=0.1)

    async def execute_task(self, goal: str, target_file: Optional[str] = None, max_retries: int = 3) -> Dict[str, Any]:
        """
        Main entry point for autonomous software engineering tasks.
        """
        logger.info(f"[CodingAgent] 🚀 Starting coding task: '{goal}' (target={target_file})")

        # 1. Scan codebase if not already scanned
        self.codebase.scan_repository(self.root_dir)

        # 2. Identify relevant file & symbol
        if not target_file:
            # Search symbols matching keywords in goal
            keywords = [w for w in re.split(r"\W+", goal) if len(w) > 3]
            matched_symbols = []
            for kw in keywords:
                matched_symbols.extend(self.codebase.find_symbol(kw))
            
            if matched_symbols:
                target_file = matched_symbols[0]["file_path"]
                target_sym = matched_symbols[0]["name"]
            else:
                target_file = os.path.join(self.root_dir, "app", "main.py")
                target_sym = "main"
        else:
            outlines = self.codebase.get_file_outline(target_file)
            target_sym = outlines[0]["name"] if outlines else "module"

        # 3. Retrieve symbol implementation
        current_code = self.codebase.get_symbol_source(target_file, target_sym)
        if not current_code:
            # Fallback to reading first 80 lines of file
            try:
                current_code = "\n".join(Path(target_file).read_text(encoding="utf-8").splitlines()[:80])
            except Exception:
                current_code = "# File could not be read directly"

        # 4. Patch loop with automated verification
        error_context = "Initial execution."
        llm = self._get_llm()

        for attempt in range(1, max_retries + 1):
            logger.info(f"[CodingAgent] 🛠️ Patch attempt {attempt}/{max_retries} on {target_file}:{target_sym}")
            try:
                prompt_text = PATCH_PROMPT.format(
                    goal=goal,
                    symbol_name=target_sym,
                    file_path=target_file,
                    current_code=current_code[:1500],
                    error_log=error_context,
                )
                response = await asyncio.to_thread(llm.invoke, prompt_text)
                
                # Clean JSON
                clean_json = response.strip()
                if clean_json.startswith("```json"):
                    clean_json = clean_json[7:]
                if clean_json.endswith("```"):
                    clean_json = clean_json[:-3]
                clean_json = clean_json.strip()

                patch_data = json.loads(clean_json)
                target_chunk = patch_data.get("target_chunk", "")
                replacement_chunk = patch_data.get("replacement_chunk", "")

                if not target_chunk or not replacement_chunk:
                    raise ValueError("Patch output missing target_chunk or replacement_chunk")

                # Apply diff
                diff_res = apply_targeted_diff(
                    file_path=target_file,
                    target_chunk=target_chunk,
                    replacement_chunk=replacement_chunk,
                )

                if not diff_res.get("success"):
                    error_context = f"Diff application error: {diff_res.get('error')}"
                    logger.warning(f"[CodingAgent] Diff failed: {error_context}")
                    continue

                # Run tests or syntax check
                test_res = run_unit_tests(target_file, cwd=self.root_dir)
                if test_res.get("success"):
                    logger.info(f"[CodingAgent] ✅ Tests passed successfully on attempt {attempt}!")
                    return {
                        "success": True,
                        "file_modified": target_file,
                        "symbol": target_sym,
                        "analysis": patch_data.get("analysis", ""),
                        "explanation": patch_data.get("explanation", ""),
                        "attempts": attempt,
                    }
                else:
                    error_context = f"Test failure output:\n{test_res.get('output', '')[:800]}"
                    logger.warning(f"[CodingAgent] Tests failed on attempt {attempt}: {error_context}")

            except Exception as e:
                error_context = f"LLM / execution exception: {e}"
                logger.error(f"[CodingAgent] Attempt {attempt} error: {e}")

        return {
            "success": False,
            "error": f"Failed to resolve coding task after {max_retries} attempts. Last error: {error_context}",
            "file": target_file,
        }


# Singleton instance
autonomous_coding_agent = AutonomousCodingAgent()
