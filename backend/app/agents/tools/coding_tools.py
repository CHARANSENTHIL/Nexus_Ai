"""
Coding Tools — LangChain & Nexus tools for Autonomous Software Engineering.
Provides AST symbol navigation, targeted diff patching, pytest execution, server lifecycle, and git.
"""
import os
import re
import sys
import subprocess
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from langchain.tools import tool

from app.agents.codebase_intelligence import codebase_intelligence

logger = logging.getLogger(__name__)

# Active background dev servers (e.g. uvicorn, nextjs)
_active_dev_servers: Dict[str, subprocess.Popen] = {}


@tool
def search_codebase_symbols(query: str) -> Dict[str, Any]:
    """Search functions, classes, and methods across the project codebase using AST indexing."""
    try:
        symbols = codebase_intelligence.find_symbol(query)
        return {
            "success": True,
            "query": query,
            "count": len(symbols),
            "symbols": symbols,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def get_file_symbol_outline(file_path: str) -> Dict[str, Any]:
    """Get the structural AST outline (functions, classes, methods) of a specific Python file."""
    try:
        outline = codebase_intelligence.get_file_outline(file_path)
        return {
            "success": True,
            "file_path": file_path,
            "symbols": outline,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def get_symbol_implementation(file_path: str, symbol_name: str) -> Dict[str, Any]:
    """Retrieve the exact implementation code of a specific function or class without reading the entire file."""
    try:
        code = codebase_intelligence.get_symbol_source(file_path, symbol_name)
        if code is not None:
            return {
                "success": True,
                "file_path": file_path,
                "symbol_name": symbol_name,
                "code": code,
            }
        return {"success": False, "error": f"Symbol '{symbol_name}' not found in {file_path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def apply_targeted_diff(file_path: str, target_chunk: str, replacement_chunk: str) -> Dict[str, Any]:
    """
    Safely replace a target code block with new code in a file.
    Validates AST syntax after modification to ensure no syntax errors were introduced.
    """
    p = Path(file_path)
    if not p.exists():
        return {"success": False, "error": f"File does not exist: {file_path}"}

    try:
        content = p.read_text(encoding="utf-8")
        if target_chunk not in content:
            # Try fuzzy newline matching
            normalized_target = target_chunk.replace("\r\n", "\n")
            normalized_content = content.replace("\r\n", "\n")
            if normalized_target not in normalized_content:
                return {
                    "success": False,
                    "error": "Target chunk not found in file. Ensure exact whitespace and line match.",
                }
            new_content = normalized_content.replace(normalized_target, replacement_chunk.replace("\r\n", "\n"), 1)
        else:
            new_content = content.replace(target_chunk, replacement_chunk, 1)

        # Validate syntax if it is a python file
        if file_path.endswith(".py"):
            import ast
            try:
                ast.parse(new_content, filename=file_path)
            except SyntaxError as syn_err:
                return {
                    "success": False,
                    "error": f"Diff produced invalid Python syntax: {syn_err}",
                }

        p.write_text(new_content, encoding="utf-8")
        # Re-index modified file
        codebase_intelligence.index_file(file_path)

        return {
            "success": True,
            "message": f"Successfully applied targeted diff to {file_path}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def run_unit_tests(test_target: str = "", cwd: Optional[str] = None) -> Dict[str, Any]:
    """Run pytest or unittest on a target test file or directory and capture stdout/tracebacks."""
    work_dir = cwd or "D:\\nexus_ai\\backend"
    cmd = [sys.executable, "-m", "pytest", test_target or ".", "-v", "--tb=short"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=120,
        )
        passed = proc.returncode == 0
        return {
            "success": passed,
            "returncode": proc.returncode,
            "output": proc.stdout[-2500:],  # Tail output
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Test run timed out after 120 seconds."}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def manage_dev_server(action: str, name: str = "app", command: str = "", port: int = 8000, cwd: Optional[str] = None) -> Dict[str, Any]:
    """
    Manage background dev servers (action: 'start', 'stop', 'status', 'health_check').
    """
    global _active_dev_servers
    work_dir = cwd or "D:\\nexus_ai\\backend"

    if action == "start":
        if name in _active_dev_servers and _active_dev_servers[name].poll() is None:
            return {"success": True, "message": f"Dev server '{name}' is already running."}

        if not command:
            command = f"{sys.executable} -m uvicorn app.main:app --port {port}"

        try:
            proc = subprocess.Popen(
                command,
                cwd=work_dir,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            _active_dev_servers[name] = proc
            return {
                "success": True,
                "message": f"Dev server '{name}' started with PID {proc.pid}",
                "port": port,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to start server: {e}"}

    elif action == "stop":
        if name in _active_dev_servers:
            proc = _active_dev_servers.pop(name)
            proc.terminate()
            return {"success": True, "message": f"Dev server '{name}' stopped."}
        return {"success": False, "message": f"Dev server '{name}' not found."}

    elif action == "status":
        running = {k: p.pid for k, p in _active_dev_servers.items() if p.poll() is None}
        return {"success": True, "running_servers": running}

    elif action == "health_check":
        import urllib.request
        url = f"http://127.0.0.1:{port}/docs" if port != 80 else "http://127.0.0.1/"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "NexusHealthCheck/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                return {"success": True, "status_code": resp.status, "message": f"Server responding at {url}"}
        except Exception as e:
            return {"success": False, "error": f"Health check failed for {url}: {e}"}

    return {"success": False, "error": f"Unknown dev server action: {action}"}
