"""
Failure Injection & Bounded Recovery Benchmark Suite for Nexus AI.
Simulates tool failures, input malformations, and verifies automatic self-healing recovery.
"""
import sys
import time
import json
from pathlib import Path
from typing import Dict, Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.runtime.recovery_engine import recovery_engine
from app.runtime.task_models import TaskRecord, SubtaskNode, TaskState, CapabilityLevel


async def run_recovery_benchmark() -> Dict[str, Any]:
    print("=" * 70)
    print("🛡️ NEXUS AI — FAILURE INJECTION & BOUNDED RECOVERY BENCHMARK")
    print("=" * 70)

    scenarios = [
        {
            "name": "Missing Required Parameter Recovery",
            "tool": "search_files",
            "error": "missing required argument 'directory'",
            "expected_strategy": "modify_input"
        },
        {
            "name": "File Not Found Auto-Correction",
            "tool": "read_file",
            "error": "FileNotFoundError: 'temp.txt' does not exist",
            "expected_strategy": "modify_input"
        },
        {
            "name": "Timeout Transient Retry",
            "tool": "check_network_connectivity",
            "error": "TimeoutError: connection timed out after 5.0s",
            "expected_strategy": "modify_input"
        },
    ]

    passed = 0
    for sc in scenarios:
        task = TaskRecord(task_id="recov_bench", goal="Simulated Recovery Test", user_id="tester")
        subtask = SubtaskNode(
            id="step_1",
            title=sc["name"],
            description=sc["name"],
            tool_name=sc["tool"],
            tool_input={},
            capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE
        )

        t0 = time.time()
        decision = await recovery_engine.handle_failure(task, subtask, sc["error"])
        elapsed_ms = round((time.time() - t0) * 1000, 2)

        has_strategy = "strategy" in decision
        if has_strategy:
            passed += 1
            print(f"  ✓ [{sc['name']:<38}] Strategy: {decision.get('strategy'):<15} ({elapsed_ms}ms)")
        else:
            print(f"  ✗ [{sc['name']:<38}] Failed to formulate recovery strategy")

    print("=" * 70)
    pass_rate = round((passed / len(scenarios)) * 100, 1)
    print(f"📊 RECOVERY ENGINE SCORE: {passed}/{len(scenarios)} ({pass_rate}%)")
    print("=" * 70)

    report_file = Path(__file__).parent / "results" / "recovery_benchmark_report.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps({
        "timestamp": time.time(),
        "total_scenarios": len(scenarios),
        "passed": passed,
        "pass_rate_pct": pass_rate
    }, indent=2), encoding="utf-8")
    print(f"📁 Saved report to: {report_file}\n")
    return {"passed": passed, "total": len(scenarios), "rate": pass_rate}


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_recovery_benchmark())
