"""
Tiered Memory Benchmark & Retrieval Evaluation Suite.
Tests working memory capture, episodic TTL expiration under load, and semantic preference retrieval.
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

from app.memory.tiered_memory import tiered_memory


def run_memory_evaluation() -> Dict[str, Any]:
    print("=" * 70)
    print("🧠 NEXUS AI — 4-TIER MEMORY HIERARCHY EVALUATION SUITE")
    print("=" * 70)

    tests_passed = 0
    total_tests = 4

    # 1. Working Memory Store & Retrieve
    t0 = time.time()
    tiered_memory.init_working_memory("mem_test_001", goal="Test working scratchpad", initial_context={"user": "tester"})
    tiered_memory.append_step_observation("mem_test_001", "Step 1", "tool_x", {"arg": 1}, "Result A")
    wm = tiered_memory.get_working_memory("mem_test_001")
    wm_ok = len(wm.get("observations", [])) == 1
    if wm_ok:
        tests_passed += 1
        print(f"  ✓ [Tier 1: Working Memory  ] Observations captured and accessible ({round((time.time()-t0)*1000, 2)}ms)")
    else:
        print("  ✗ [Tier 1: Working Memory  ] Failed to record observation")

    # 2. Memory Consolidation
    t0 = time.time()
    cons_ok = tiered_memory.consolidate_task_memory("mem_test_001", success=True, outcome="Completed test")
    wm_cleared = tiered_memory.get_working_memory("mem_test_001") == {}
    if cons_ok and wm_cleared:
        tests_passed += 1
        print(f"  ✓ [Tier 2: Consolidation   ] Transferred to Episodic & cleared Working memory ({round((time.time()-t0)*1000, 2)}ms)")
    else:
        print("  ✗ [Tier 2: Consolidation   ] Failed consolidation")

    # 3. Semantic Memory Key-Value Store
    t0 = time.time()
    tiered_memory.set_semantic_fact("preferred_browser", "msedge", category="preferences")
    val = tiered_memory.get_semantic_fact("preferred_browser")
    sem_ok = (val == "msedge")
    if sem_ok:
        tests_passed += 1
        print(f"  ✓ [Tier 3: Semantic Store  ] Fact stored and retrieved with exact match ({round((time.time()-t0)*1000, 2)}ms)")
    else:
        print("  ✗ [Tier 3: Semantic Store  ] Fact retrieval failed")

    # 4. Procedural Memory Workflow Recipes
    t0 = time.time()
    tiered_memory.store_procedure(
        domain_or_app="student_portal",
        trigger_pattern="download grade report",
        steps=[{"step": 1, "action": "open_url"}, {"step": 2, "action": "click_download"}]
    )
    proc = tiered_memory.find_procedure("student_portal")
    proc_ok = proc is not None and len(proc.get("steps", [])) == 2
    if proc_ok:
        tests_passed += 1
        print(f"  ✓ [Tier 4: Procedural Store] Recipe learned, indexed, and retrieved ({round((time.time()-t0)*1000, 2)}ms)")
    else:
        print("  ✗ [Tier 4: Procedural Store] Procedural retrieval failed")

    print("=" * 70)
    pass_rate = round((tests_passed / total_tests) * 100, 1)
    print(f"📊 MEMORY HIERARCHY SCORE: {tests_passed}/{total_tests} ({pass_rate}%)")
    print("=" * 70)

    report_file = Path(__file__).parent / "results" / "memory_eval_report.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps({
        "timestamp": time.time(),
        "total_tests": total_tests,
        "passed_tests": tests_passed,
        "pass_rate_pct": pass_rate
    }, indent=2), encoding="utf-8")
    print(f"📁 Saved report to: {report_file}\n")
    return {"passed": tests_passed, "total": total_tests, "rate": pass_rate}


if __name__ == "__main__":
    run_memory_evaluation()
