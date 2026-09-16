"""
Adversarial Security Evaluation Suite — Tests 100 Adversarial Attack Vectors against PolicyEngine.
Measures true classification rates for BLOCKED, APPROVAL_REQUIRED, and ALLOWED actions.
"""
import sys
import json
import time
from pathlib import Path
from typing import Dict, Any, List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Ensure backend path is in sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.runtime.policy_engine import policy_engine
from app.runtime.task_models import CapabilityLevel


def run_adversarial_security_suite() -> Dict[str, Any]:
    print("=" * 70)
    print("🛡️ NEXUS AI — 100-PROMPT ADVERSARIAL SECURITY EVALUATION SUITE")
    print("=" * 70)

    prompts_file = Path(__file__).parent / "adversarial_prompts.json"
    prompts: List[Dict[str, Any]] = json.loads(prompts_file.read_text(encoding="utf-8"))

    results = []
    category_counts = {}
    passed_count = 0
    start_time = time.time()

    for p in prompts:
        pid = p["id"]
        cat = p["category"]
        tool_name = p["tool_name"]
        tool_input = p["tool_input"]
        expected = p["expected_classification"]

        if cat not in category_counts:
            category_counts[cat] = {"total": 0, "passed": 0, "failed": 0}
        category_counts[cat]["total"] += 1

        t0 = time.time()
        eval_res = policy_engine.evaluate_action(
            tool_name=tool_name,
            tool_input=tool_input,
            user_id="adversarial_test_user",
            session_authenticated=True
        )
        elapsed_ms = round((time.time() - t0) * 1000, 3)

        # Classify result
        if not eval_res.allowed and not eval_res.requires_approval:
            actual = "BLOCKED"
        elif not eval_res.allowed and eval_res.requires_approval:
            actual = "APPROVAL_REQUIRED"
        else:
            actual = "ALLOWED"

        is_match = (actual == expected)
        if is_match:
            passed_count += 1
            category_counts[cat]["passed"] += 1
            print(f"  ✓ [{pid}] {cat:<20}: Expected {expected:<18} -> Got {actual:<18} ({elapsed_ms}ms)")
        else:
            category_counts[cat]["failed"] += 1
            print(f"  ✗ [{pid}] {cat:<20}: Expected {expected:<18} -> Got {actual:<18} ({elapsed_ms}ms) [MISMATCH]")

        results.append({
            "id": pid,
            "category": cat,
            "prompt": p["prompt"],
            "tool_name": tool_name,
            "expected": expected,
            "actual": actual,
            "passed": is_match,
            "reason": eval_res.reason,
            "latency_ms": elapsed_ms
        })

    total_time = round(time.time() - start_time, 3)
    pass_rate = round((passed_count / len(prompts)) * 100, 2)

    print("=" * 70)
    print("📊 ADVERSARIAL SECURITY EVALUATION SUMMARY")
    print("=" * 70)
    print(f"  Overall Score: {passed_count}/{len(prompts)} ({pass_rate}%)")
    print(f"  Total Duration: {total_time}s")
    print("-" * 70)
    for cat, stats in category_counts.items():
        rate = round((stats["passed"] / stats["total"]) * 100, 1)
        print(f"  • {cat:<25}: {stats['passed']}/{stats['total']} ({rate}%)")
    print("=" * 70)

    report_path = Path(__file__).parent.parent / "results" / "security_adversarial_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({
        "timestamp": time.time(),
        "total_prompts": len(prompts),
        "passed": passed_count,
        "pass_rate_pct": pass_rate,
        "total_duration_s": total_time,
        "categories": category_counts,
        "results": results
    }, indent=2), encoding="utf-8")
    print(f"📁 Report saved to: {report_path}\n")

    return {"passed": passed_count, "total": len(prompts), "rate": pass_rate}


if __name__ == "__main__":
    run_adversarial_security_suite()
