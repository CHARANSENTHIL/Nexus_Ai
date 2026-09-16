"""
Evaluation Metrics Aggregator for Nexus AI Autonomous Task Benchmark.
Calculates task success rate, completion latency, tool calls, retries, recovery rate, and policy violations.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List
import statistics


@dataclass
class TaskMetric:
    task_id: str
    domain: str
    goal: str
    passed: bool
    completion_time_ms: float
    tool_calls_count: int = 1
    retry_count: int = 0
    recovered: bool = False
    human_intervened: bool = False
    policy_violation_prevented: bool = False
    error: str = ""


@dataclass
class BenchmarkSummary:
    total_tasks: int = 0
    passed_tasks: int = 0
    failed_tasks: int = 0
    pass_rate_pct: float = 0.0
    total_tool_calls: int = 0
    total_retries: int = 0
    total_recoveries: int = 0
    total_human_interventions: int = 0
    total_policy_violations_blocked: int = 0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    domain_scores: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def compute(cls, metrics: List[TaskMetric]) -> "BenchmarkSummary":
        if not metrics:
            return cls()

        total = len(metrics)
        passed = sum(1 for m in metrics if m.passed)
        failed = total - passed
        pass_rate = round((passed / total) * 100, 2)

        latencies = [m.completion_time_ms for m in metrics]
        latencies.sort()
        p50 = round(statistics.median(latencies), 3) if latencies else 0.0
        p95_idx = int(len(latencies) * 0.95)
        p95 = round(latencies[min(p95_idx, len(latencies) - 1)], 3) if latencies else 0.0

        tool_calls = sum(m.tool_calls_count for m in metrics)
        retries = sum(m.retry_count for m in metrics)
        recoveries = sum(1 for m in metrics if m.recovered)
        human_ints = sum(1 for m in metrics if m.human_intervened)
        policy_viols = sum(1 for m in metrics if m.policy_violation_prevented)

        domains: Dict[str, Dict[str, Any]] = {}
        for m in metrics:
            if m.domain not in domains:
                domains[m.domain] = {"total": 0, "passed": 0, "failed": 0}
            domains[m.domain]["total"] += 1
            if m.passed:
                domains[m.domain]["passed"] += 1
            else:
                domains[m.domain]["failed"] += 1

        for d, s in domains.items():
            s["pass_rate_pct"] = round((s["passed"] / s["total"]) * 100, 1)

        return cls(
            total_tasks=total,
            passed_tasks=passed,
            failed_tasks=failed,
            pass_rate_pct=pass_rate,
            total_tool_calls=tool_calls,
            total_retries=retries,
            total_recoveries=recoveries,
            total_human_interventions=human_ints,
            total_policy_violations_blocked=policy_viols,
            latency_p50_ms=p50,
            latency_p95_ms=p95,
            domain_scores=domains
        )
