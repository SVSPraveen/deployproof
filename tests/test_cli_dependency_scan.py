"""Tests for Dependency & Slopsquatting scanner CLI wiring and report formatting."""

import subprocess
from pathlib import Path
from unittest.mock import patch
from deployproof.cli import main
from deployproof.dependencies import (
    DependencyCheckResult,
    DependencyScanSummary,
    ExtractedDependency,
)
from deployproof.mutator import MutationResult
from deployproof.reporter import format_report
from deployproof.secrets import SecretsScanResult
from deployproof.symlinks import SymlinkScanResult


def test_format_report_with_high_risk_dependency(tmp_path: Path):
    file_p = tmp_path / "app.py"
    dep_summary = DependencyScanSummary(
        total_scanned=2,
        high_risk_count=1,
        medium_risk_count=0,
        ok_count=1,
        unknown_count=0,
        findings=[
            DependencyCheckResult(
                package_name="hallucinated-agent-tool",
                import_name="hallucinated_agent_tool",
                source_file=file_p,
                lineno=3,
                source_type="import",
                status="HIGH_RISK",
                age_days=None,
                first_release_date=None,
                details="Package does NOT exist on PyPI (HTTP 404) - hallucinated package name / slopsquatting vulnerability",
            ),
            DependencyCheckResult(
                package_name="requests",
                import_name="requests",
                source_file=file_p,
                lineno=1,
                source_type="import",
                status="OK",
                age_days=5000,
                first_release_date="2011-02-14",
                details="Established package (5000 days old, first published 2011-02-14)",
            ),
        ],
        duration_seconds=0.1,
    )

    mut_res = MutationResult(
        total_mutants=0,
        killed_mutants=0,
        survived_mutants=[],
        untested_files=[],
        runner_errors=[],
        skipped_constructs=[],
        mutation_score=100.0,
        duration_seconds=0.1,
        files_tested=[],
    )

    report = format_report(
        result=mut_res,
        target_files=[],
        dependency_result=dep_summary,
        repo_root=tmp_path,
    )

    assert "Dependency & Slopsquatting Scan (PyPI Registry & Age Analysis):" in report
    assert "[1] hallucinated-agent-tool [HIGH_RISK]" in report
    assert "Classification: HIGH RISK (Package does NOT exist on PyPI)" in report
    assert "SECURITY ALERT: 1 non-existent / hallucinated package(s) detected. Fix imports before pushing." in report
    # Established package requests is OK so not printed individually to keep output short
    assert "[2] requests" not in report


def test_format_report_with_medium_risk_dependency(tmp_path: Path):
    file_p = tmp_path / "app.py"
    dep_summary = DependencyScanSummary(
        total_scanned=1,
        high_risk_count=0,
        medium_risk_count=1,
        ok_count=0,
        unknown_count=0,
        findings=[
            DependencyCheckResult(
                package_name="brand-new-pkg",
                import_name="brand_new_pkg",
                source_file=file_p,
                lineno=5,
                source_type="import",
                status="MEDIUM_RISK",
                age_days=3,
                first_release_date="2026-08-25",
                details="Recently registered package (3 days old, first published 2026-08-25) - potential slopsquat / supply chain risk",
            )
        ],
        duration_seconds=0.1,
    )

    mut_res = MutationResult(
        total_mutants=0,
        killed_mutants=0,
        survived_mutants=[],
        untested_files=[],
        runner_errors=[],
        skipped_constructs=[],
        mutation_score=100.0,
        duration_seconds=0.1,
        files_tested=[],
    )

    report = format_report(
        result=mut_res,
        target_files=[],
        dependency_result=dep_summary,
        repo_root=tmp_path,
    )

    assert "[!] 1 suspicious dependency finding detected:" in report
    assert "[1] brand-new-pkg [MEDIUM_RISK]" in report
    assert "Registered 3 days ago" in report


def test_cli_blocks_on_high_risk_dependency(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, capture_output=True, check=True)

    app_py = tmp_path / "app.py"
    app_py.write_text("import hallucinated_fake_dependency_xyz\n", encoding="utf-8")

    # Mock PyPI to return 404 for hallucinated_fake_dependency_xyz
    with patch("deployproof.dependencies.query_pypi_registry") as mock_query:
        mock_query.return_value = (
            "HIGH_RISK",
            None,
            None,
            "Package does NOT exist on PyPI (HTTP 404)",
        )
        exit_code = main(["check", "--files", str(app_py)])
        assert exit_code == 1


def test_format_report_with_unscanned_dependency_source(tmp_path: Path):
    req_file = tmp_path / "requirements.txt"
    dep_summary = DependencyScanSummary(
        total_scanned=2,
        high_risk_count=0,
        medium_risk_count=0,
        ok_count=1,
        unknown_count=0,
        findings=[
            DependencyCheckResult(
                package_name="requests",
                import_name="requests",
                source_file=req_file,
                lineno=1,
                source_type="requirements.txt",
                status="OK",
                age_days=5000,
                first_release_date="2011-02-14",
                details="Established package",
            ),
            DependencyCheckResult(
                package_name="-r base.txt",
                import_name="-r base.txt",
                source_file=req_file,
                lineno=2,
                source_type="requirements.txt",
                status="UNSCANNED",
                age_days=None,
                first_release_date=None,
                details="External requirements file include (-r) - seen, not checked",
            ),
        ],
        duration_seconds=0.1,
        unscanned_count=1,
    )

    mut_res = MutationResult(
        total_mutants=0,
        killed_mutants=0,
        survived_mutants=[],
        untested_files=[],
        runner_errors=[],
        skipped_constructs=[],
        mutation_score=100.0,
        duration_seconds=0.1,
        files_tested=[],
    )

    report = format_report(
        result=mut_res,
        target_files=[],
        dependency_result=dep_summary,
        repo_root=tmp_path,
    )

    assert "1 unscanned dependency source (seen, not checked):" in report
    assert "* -r base.txt (Source: requirements.txt:2) - External requirements file include (-r) - seen, not checked" in report

