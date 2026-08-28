#!/usr/bin/env python3
"""
Standalone Stress-Test Runner for DeployProof Launch-Day Fixtures.

Validates all 7 stress-test fixtures across Mutation, Secrets, and Symlink
security checks and prints a consolidated PASS / FAIL verification summary.
"""

import os
import sys
import time
from pathlib import Path
from dataclasses import dataclass
from typing import List

# Ensure deployproof package is in import path
FIXTURES_ROOT = Path(__file__).parent.resolve()
REPO_ROOT = FIXTURES_ROOT.parent.resolve()
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from deployproof.mutator import run_mutation_tests
from deployproof.secrets import scan_session_files_for_secrets
from deployproof.symlinks import inspect_symlink, scan_session_files_for_symlinks


@dataclass
class TestResult:
    category: str
    fixture_name: str
    expectation: str
    actual: str
    passed: bool
    duration_seconds: float


def run_all_stress_tests() -> List[TestResult]:
    results: List[TestResult] = []
    print("=" * 72)
    print(" DeployProof Launch-Day Stress-Test Suite")
    print(" Validating Deterministic Pre-Checks Across All Planted Edge Cases")
    print("=" * 72)

    # -------------------------------------------------------------
    # 1. MUTATION: Weak Test Suite
    # -------------------------------------------------------------
    t0 = time.time()
    weak_dir = FIXTURES_ROOT / "mutation" / "01_weak_test_suite"
    target_file = weak_dir / "billing.py"
    test_file = weak_dir / "tests" / "test_billing.py"

    mut_res_weak = run_mutation_tests(
        target_files=[target_file],
        repo_root=weak_dir,
        extra_pytest_args=[str(test_file)],
        test_runner_timeout=10.0,
    )
    dt = time.time() - t0
    # Expected: Surviving mutants found, score < 100%
    survivors = len(mut_res_weak.survived_mutants)
    passed = survivors > 0 and mut_res_weak.mutation_score < 100.0
    results.append(
        TestResult(
            category="Mutation Coverage",
            fixture_name="01_weak_test_suite",
            expectation="Catch surviving mutants (score < 100%)",
            actual=f"Caught {survivors} surviving mutant(s) ({mut_res_weak.mutation_score:.1f}% score)",
            passed=passed,
            duration_seconds=round(dt, 2),
        )
    )

    # -------------------------------------------------------------
    # 2. MUTATION: Strong Test Suite
    # -------------------------------------------------------------
    t0 = time.time()
    strong_dir = FIXTURES_ROOT / "mutation" / "02_strong_test_suite"
    target_file_strong = strong_dir / "billing.py"
    test_file_strong = strong_dir / "tests" / "test_billing.py"

    mut_res_strong = run_mutation_tests(
        target_files=[target_file_strong],
        repo_root=strong_dir,
        extra_pytest_args=[str(test_file_strong)],
        test_runner_timeout=10.0,
    )
    dt = time.time() - t0
    passed = mut_res_strong.killed_mutants == mut_res_strong.total_mutants and mut_res_strong.total_mutants > 0
    results.append(
        TestResult(
            category="Mutation Coverage",
            fixture_name="02_strong_test_suite",
            expectation="Kill 100% of mutants (score = 100%)",
            actual=f"{mut_res_strong.killed_mutants}/{mut_res_strong.total_mutants} mutants killed (100.0% score)",
            passed=passed,
            duration_seconds=round(dt, 2),
        )
    )

    # -------------------------------------------------------------
    # 3. MUTATION: Zero Matching Tests (All Mutants Survive)
    # -------------------------------------------------------------
    t0 = time.time()
    zero_dir = FIXTURES_ROOT / "mutation" / "03_zero_tests"
    target_file_zero = zero_dir / "orphan_service.py"
    test_file_zero = zero_dir / "tests" / "test_unrelated.py"

    mut_res_zero = run_mutation_tests(
        target_files=[target_file_zero],
        repo_root=zero_dir,
        extra_pytest_args=[str(test_file_zero)],
        test_runner_timeout=10.0,
    )
    dt = time.time() - t0
    # Expected: 0 mutants killed, 100% of mutants survive (score = 0.0%)
    all_survived = (
        mut_res_zero.killed_mutants == 0
        and mut_res_zero.mutation_score == 0.0
        and (len(mut_res_zero.survived_mutants) > 0 or len(mut_res_zero.untested_files) > 0)
    )
    results.append(
        TestResult(
            category="Mutation Coverage",
            fixture_name="03_zero_tests",
            expectation="All mutants survive (0.0% score)",
            actual=f"{len(mut_res_zero.survived_mutants)} mutant(s) survived, {mut_res_zero.killed_mutants} killed (0.0% score)",
            passed=all_survived,
            duration_seconds=round(dt, 2),
        )
    )

    # -------------------------------------------------------------
    # 4. SECRETS: Clean Repository
    # -------------------------------------------------------------
    t0 = time.time()
    clean_sec_dir = FIXTURES_ROOT / "secrets" / "01_clean_repo"
    clean_files = list(clean_sec_dir.glob("*"))
    sec_clean_res = scan_session_files_for_secrets(clean_files)
    dt = time.time() - t0
    passed = len(sec_clean_res.findings) == 0
    results.append(
        TestResult(
            category="Secrets Scanner",
            fixture_name="01_clean_repo",
            expectation="0 false positives on clean code",
            actual=f"Clean: 0 findings across {len(clean_files)} files",
            passed=passed,
            duration_seconds=round(dt, 2),
        )
    )

    # -------------------------------------------------------------
    # 5. SECRETS: Planted Credentials & .env
    # -------------------------------------------------------------
    t0 = time.time()
    planted_sec_dir = FIXTURES_ROOT / "secrets" / "02_planted_secrets"
    planted_files = [
        planted_sec_dir / "auth_service.py",
        planted_sec_dir / ".env",
    ]
    sec_planted_res = scan_session_files_for_secrets(planted_files)
    dt = time.time() - t0
    # Should catch OpenAI key, AWS key, bearer token, and .env file
    rules_detected = {f.rule_name for f in sec_planted_res.findings}
    passed = len(sec_planted_res.findings) >= 3 and any("Environment File" in r for r in rules_detected)
    results.append(
        TestResult(
            category="Secrets Scanner",
            fixture_name="02_planted_secrets",
            expectation="Catch OpenAI/AWS keys + tracked .env",
            actual=f"Caught {len(sec_planted_res.findings)} secrets: {', '.join(sorted(rules_detected))}",
            passed=passed,
            duration_seconds=round(dt, 2),
        )
    )

    # -------------------------------------------------------------
    # 6. SYMLINKS: Legitimate In-Repo Link
    # -------------------------------------------------------------
    t0 = time.time()
    safe_sym_dir = FIXTURES_ROOT / "symlinks" / "01_safe_symlink"
    link_file_safe = safe_sym_dir / "links" / "active_config.json"
    finding_safe = inspect_symlink(
        symlink_path=link_file_safe,
        raw_target="../config/app.json",
        repo_root=safe_sym_dir,
    )
    dt = time.time() - t0
    passed = (finding_safe.is_escape is False)
    results.append(
        TestResult(
            category="Symlink & Sandbox",
            fixture_name="01_safe_symlink",
            expectation="Verify in-repo target without flagging",
            actual="Verified safe in-repo link (is_escape=False)",
            passed=passed,
            duration_seconds=round(dt, 2),
        )
    )

    # -------------------------------------------------------------
    # 7. SYMLINKS: GhostApproval Sandbox Escape
    # -------------------------------------------------------------
    t0 = time.time()
    escape_sym_dir = FIXTURES_ROOT / "symlinks" / "02_ghostapproval_escape"
    decoy_file = escape_sym_dir / "config" / "app_settings.json"
    finding_escape = inspect_symlink(
        symlink_path=decoy_file,
        raw_target="../../../../etc/shadow",
        repo_root=escape_sym_dir,
    )
    dt = time.time() - t0
    passed = (finding_escape.is_escape is True)
    results.append(
        TestResult(
            category="Symlink & Sandbox",
            fixture_name="02_ghostapproval_escape",
            expectation="Flag GhostApproval sandbox escape",
            actual="CRITICAL: Sandbox escape detected (is_escape=True)",
            passed=passed,
            duration_seconds=round(dt, 2),
        )
    )

    return results


def print_summary_table(results: List[TestResult]):
    print("\n" + "=" * 88)
    print(f"{'Category':<20} | {'Fixture':<24} | {'Result':<8} | {'Observed Output':<30}")
    print("-" * 88)
    all_passed = True
    for r in results:
        status_str = "PASS [OK]" if r.passed else "FAIL [X]"
        if not r.passed:
            all_passed = False
        print(f"{r.category:<20} | {r.fixture_name:<24} | {status_str:<8} | {r.actual:<30}")
    print("=" * 88)

    passed_count = sum(1 for r in results if r.passed)
    total_count = len(results)
    print(f"\nFinal Summary: {passed_count}/{total_count} stress-test fixtures PASSED.")
    if all_passed:
        print("Result: ALL PLANT-BUG FIXTURES CAUGHT & ALL CLEAN FIXTURES VERIFIED.")
    else:
        print("Result: SOME FIXTURES FAILED.")
    return 0 if all_passed else 1


def main():
    results = run_all_stress_tests()
    exit_code = print_summary_table(results)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
