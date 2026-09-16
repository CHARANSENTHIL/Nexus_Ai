"""
Benchmark Reporter — Formats and exports markdown and JSON evaluation reports.
"""
import json
import time
from pathlib import Path
from typing import List
from evals.metrics import BenchmarkSummary, TaskMetric


class BenchmarkReporter:
    def __init__(self, summary: BenchmarkSummary, metrics: List[TaskMetric]):
        self.summary = summary
        self.metrics = metrics

    def print_summary(self):
        print("=" * 70)
        print("📊 AUTONOMOUS TASK BENCHMARK SUMMARY REPORT")
        print("=" * 70)
        print(f"  Overall Score:           {self.summary.passed_tasks}/{self.summary.total_tasks} ({self.summary.pass_rate_pct}%)")
        print(f"  Latency (p50):           {self.summary.latency_p50_ms} ms")
        print(f"  Latency (p95):           {self.summary.latency_p95_ms} ms")
        print(f"  Total Tool Calls:        {self.summary.total_tool_calls}")
        print(f"  Total Retries:           {self.summary.total_retries}")
        print(f"  Total Human Handoffs:    {self.summary.total_human_interventions}")
        print(f"  Policy Violations Saved: {self.summary.total_policy_violations_blocked}")
        print("-" * 70)
        for domain, stats in self.summary.domain_scores.items():
            print(f"  • {domain.capitalize():<18}: {stats['passed']}/{stats['total']} ({stats['pass_rate_pct']}%)")
        print("=" * 70)

    def save_json_report(self, output_file: Path = Path(__file__).parent / "results" / "yaml_benchmark_report.json"):
        output_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "timestamp": time.time(),
            "summary": {
                "total_tasks": self.summary.total_tasks,
                "passed_tasks": self.summary.passed_tasks,
                "pass_rate_pct": self.summary.pass_rate_pct,
                "latency_p50_ms": self.summary.latency_p50_ms,
                "latency_p95_ms": self.summary.latency_p95_ms,
                "domain_scores": self.summary.domain_scores
            },
            "tasks": [
                {
                    "id": m.task_id,
                    "domain": m.domain,
                    "goal": m.goal,
                    "passed": m.passed,
                    "latency_ms": m.completion_time_ms,
                    "human_intervened": m.human_intervened,
                    "policy_blocked": m.policy_violation_prevented
                }
                for m in self.metrics
            ]
        }
        output_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"📁 Saved JSON report to: {output_file}")

    def save_markdown_report(self, output_file: Path = Path(__file__).parent / "results" / "benchmark_summary.md"):
        output_file.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# 📊 Nexus AI — Autonomous Task Benchmark Evaluation Matrix",
            f"**Total Tasks Evaluated**: {self.summary.total_tasks} | **Overall Pass Rate**: {self.summary.pass_rate_pct}%",
            f"**Latency**: p50 = {self.summary.latency_p50_ms}ms, p95 = {self.summary.latency_p95_ms}ms",
            "",
            "## Domain Performance",
            "| Domain | Total | Passed | Pass Rate |",
            "| :--- | :---: | :---: | :---: |"
        ]
        for d, s in self.summary.domain_scores.items():
            lines.append(f"| **{d.capitalize()}** | {s['total']} | {s['passed']} | **{s['pass_rate_pct']}%** |")

        output_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"📁 Saved Markdown report to: {output_file}")
