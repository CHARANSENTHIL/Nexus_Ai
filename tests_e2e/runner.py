"""
tests_e2e/runner.py - CLI Runner for E2E Test Suite (Tiers 1-4)

Supports test discovery, tier filtering, requirement filtering, formatted ASCII summary output,
JSON report exports, and returns exit code 0 when 100% of tests pass.
"""

import argparse
import inspect
import json
import os
import sys
import time
import unittest
from typing import Dict, List, Any, Optional

# Insert project root directory into sys.path before importing tests_e2e modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import test modules explicitly
from tests_e2e import test_tier1, test_tier2, test_tier3, test_tier4


class TestResultRecord:
    def __init__(self, name: str, tier: int, feature: str, passed: bool, duration_ms: float, error: Optional[str] = None):
        self.name = name
        self.tier = tier
        self.feature = feature
        self.passed = passed
        self.duration_ms = duration_ms
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "tier": self.tier,
            "feature": self.feature,
            "passed": self.passed,
            "duration_ms": round(self.duration_ms, 2),
            "error": self.error
        }


class E2ETestRunner:
    """Discovers, filters, executes, and reports on E2E test cases across Tiers 1-4."""

    def __init__(self, tier: Optional[int] = None, feature: Optional[str] = None, verbose: bool = False, json_out: Optional[str] = None):
        self.tier_filter = tier
        self.feature_filter = feature.upper() if feature else None
        self.verbose = verbose
        self.json_out = json_out
        self.results: List[TestResultRecord] = []

    def _determine_tier_and_feature(self, test_case: unittest.TestCase) -> tuple[int, str]:
        module_name = test_case.__class__.__module__
        method_name = test_case._testMethodName
        
        tier = 1
        if "tier1" in module_name:
            tier = 1
        elif "tier2" in module_name:
            tier = 2
        elif "tier3" in module_name:
            tier = 3
        elif "tier4" in module_name:
            tier = 4

        # Extract feature ID (R1-R8)
        feature = "R1-R8"
        method_lower = method_name.lower()
        for r_num in range(1, 9):
            r_str = f"r{r_num}"
            if f"_r{r_num}_" in method_lower or f"_r{r_num}" in method_lower or f"r{r_num}_" in method_lower:
                feature = f"R{r_num}"
                break

        if feature == "R1-R8" and tier in (3, 4):
            feature = "CROSS-MODULE"

        return tier, feature

    def discover_tests(self) -> List[tuple[unittest.TestCase, int, str]]:
        discovered = []
        modules = [
            (1, test_tier1.TestTier1FeatureCoverage),
            (2, test_tier2.TestTier2BoundaryCases),
            (3, test_tier3.TestTier3CrossFeatureInteractions),
            (4, test_tier4.TestTier4RealWorldScenarios),
        ]

        for default_tier, test_class in modules:
            suite = unittest.TestLoader().loadTestsFromTestCase(test_class)
            for test in suite:
                tier, feature = self._determine_tier_and_feature(test)
                if tier == default_tier:
                    pass  # Use detected
                
                # Apply Filters
                if self.tier_filter is not None and tier != self.tier_filter:
                    continue
                if self.feature_filter is not None and self.feature_filter not in feature:
                    continue

                discovered.append((test, tier, feature))

        return discovered

    def run_suite(self) -> bool:
        start_time = time.time()
        tests = self.discover_tests()

        print("\n" + "=" * 80)
        print("  NEXUS AI - END-TO-END (E2E) TEST SUITE RUNNER")
        print("=" * 80)
        if self.tier_filter:
            print(f" Filter Active: Tier {self.tier_filter}")
        if self.feature_filter:
            print(f" Filter Active: Requirement {self.feature_filter}")
        print(f" Discovered {len(tests)} test cases across target scope.\n")

        all_passed = True

        for test, tier, feature in tests:
            test_name = f"{test.__class__.__name__}.{test._testMethodName}"
            if self.verbose:
                print(f"Running [Tier {tier} | {feature}] {test._testMethodName} ... ", end="", flush=True)

            t0 = time.time()
            result_obj = unittest.TestResult()
            test.run(result_obj)
            elapsed_ms = (time.time() - t0) * 1000.0

            passed = result_obj.wasSuccessful()
            err_msg = None
            if not passed:
                all_passed = False
                err_list = result_obj.errors or result_obj.failures
                if err_list:
                    err_msg = str(err_list[0][1])

            record = TestResultRecord(
                name=test_name,
                tier=tier,
                feature=feature,
                passed=passed,
                duration_ms=elapsed_ms,
                error=err_msg
            )
            self.results.append(record)

            if self.verbose:
                status_str = "\033[92mPASS\033[0m" if passed else "\033[91mFAIL\033[0m"
                print(f"{status_str} ({elapsed_ms:.1f}ms)")
                if err_msg:
                    print(f"    Error: {err_msg.splitlines()[-1]}")
            else:
                sys.stdout.write("." if passed else "F")
                sys.stdout.flush()

        if not self.verbose:
            print("\n")

        total_time_s = time.time() - start_time
        self.format_terminal_summary(total_time_s)

        if self.json_out:
            self.export_json_report(self.json_out)

        return all_passed

    def format_terminal_summary(self, total_time_s: float) -> None:
        print("\n" + "=" * 80)
        print("                        E2E TEST EXECUTION SUMMARY MATRIX")
        print("=" * 80)

        # Tier breakdown
        tier_counts = {1: {"total": 0, "passed": 0}, 2: {"total": 0, "passed": 0}, 3: {"total": 0, "passed": 0}, 4: {"total": 0, "passed": 0}}
        feature_counts: Dict[str, Dict[str, int]] = {}

        for r in self.results:
            tier_counts[r.tier]["total"] += 1
            if r.passed:
                tier_counts[r.tier]["passed"] += 1

            if r.feature not in feature_counts:
                feature_counts[r.feature] = {"total": 0, "passed": 0}
            feature_counts[r.feature]["total"] += 1
            if r.passed:
                feature_counts[r.feature]["passed"] += 1

        print(f"{'Tier':<10} | {'Scope / Description':<35} | {'Passed / Total':<18} | {'Status':<8}")
        print("-" * 80)
        tier_names = {
            1: "Tier 1: Feature Coverage (R1-R8)",
            2: "Tier 2: Boundary & Corner Cases",
            3: "Tier 3: Cross-Feature Interactions",
            4: "Tier 4: Real-World Scenarios"
        }

        total_all = len(self.results)
        passed_all = sum(1 for r in self.results if r.passed)

        for t_id in range(1, 5):
            t_data = tier_counts[t_id]
            if t_data["total"] > 0:
                st = "READY" if t_data["passed"] == t_data["total"] else "FAILED"
                pct = (t_data["passed"] / t_data["total"]) * 100
                ratio_str = f"{t_data['passed']} / {t_data['total']} ({pct:.0f}%)"
                tier_str = f"Tier {t_id}"
                print(f"{tier_str:<10} | {tier_names[t_id]:<35} | {ratio_str:<18} | {st:<8}")

        print("-" * 80)
        final_status = "100% PASS" if (total_all > 0 and passed_all == total_all) else "FAILED"
        pct_all = (passed_all / max(1, total_all)) * 100
        ratio_all_str = f"{passed_all} / {total_all} ({pct_all:.0f}%)"
        print(f"{'TOTAL':<10} | {'Full System E2E Scope':<35} | {ratio_all_str:<18} | {final_status:<8}")
        print("=" * 80)
        print(f" Total Execution Time: {total_time_s:.2f} seconds")
        print("=" * 80 + "\n")

    def export_json_report(self, path: str) -> None:
        report = {
            "timestamp": time.time(),
            "total_tests": len(self.results),
            "passed_tests": sum(1 for r in self.results if r.passed),
            "failed_tests": sum(1 for r in self.results if not r.passed),
            "results": [r.to_dict() for r in self.results]
        }
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"JSON test report saved to {path}")


def main():
    parser = argparse.ArgumentParser(description="Nexus AI E2E Test Suite Runner")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3, 4], help="Filter execution by specific Tier (1-4)")
    parser.add_argument("--feature", type=str, help="Filter execution by requirement ID (R1-R8)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose test output")
    parser.add_argument("--json-out", type=str, help="Path to write JSON test report")
    args = parser.parse_args()

    runner = E2ETestRunner(tier=args.tier, feature=args.feature, verbose=args.verbose, json_out=args.json_out)
    success = runner.run_suite()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
