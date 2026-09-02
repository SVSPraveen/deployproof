"""Unit and integration tests for GitHub Actions CI integration."""
import os
from pathlib import Path
import pytest

from deployproof.ci import (
    format_github_annotations,
    format_github_step_summary,
    is_github_actions,
    write_github_step_summary_if_enabled,
)
from deployproof.mutator import Mutant, MutationResult
from deployproof.secrets import SecretFinding, SecretsScanResult
from deployproof.symlinks import SymlinkFinding, SymlinkScanResult
from deployproof.sast import SastFinding, SastScanResult


def test_is_github_actions_detection(monkeypatch):
    """Verify is_github_actions detects GitHub Actions environment variables."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert is_github_actions() is False

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert is_github_actions() is True


def test_format_github_annotations(tmp_path: Path):
    """Verify format_github_annotations outputs valid GitHub Actions workflow commands."""
    sample_py = tmp_path / "auth.py"
    sample_py.write_text("def login(): pass\n", encoding="utf-8")

    mutant = Mutant(
        mutant_id="auth.py:1:mut_1",
        file_path=sample_py,
        line_number=1,
        description="Replace return value with None",
        original_line="return True",
        mutated_line="return None",
        mutated_source="",
        status="SURVIVED",
    )

    res = MutationResult(
        total_mutants=1,
        killed_mutants=0,
        survived_mutants=[mutant],
        untested_files=[],
        runner_errors=[],
        skipped_constructs=[],
        mutation_score=0.0,
        duration_seconds=1.0,
        files_tested=[sample_py],
    )

    secrets_res = SecretsScanResult(
        findings=[
            SecretFinding(
                file_path=sample_py,
                line_number=1,
                rule_name="Hardcoded Secret",
                redacted_value="AKIA***",
                snippet="key = 'AKIA123'",
                description="AWS Access Key detected",
            )
        ],
        files_scanned=1,
    )

    sast_res = SastScanResult(
        findings=[
            SastFinding(
                file_path=sample_py,
                line_number=1,
                rule_id="sast_sql_injection",
                rule_name="SQL Injection",
                severity="CRITICAL",
                snippet="cursor.execute(f'SELECT * FROM users WHERE id={user_id}')",
                description="Unsanitized string interpolation in SQL query",
                cwe="CWE-89",
                owasp_category="A03:2021-Injection",
            )
        ],
        files_scanned=1,
        clean=False,
    )

    annotations = format_github_annotations(
        result=res,
        target_files=[sample_py],
        secrets_result=secrets_res,
        sast_result=sast_res,
        repo_root=tmp_path,
    )

    assert len(annotations) == 3
    # Secret annotation (::error)
    assert any("::error file=auth.py,line=1,title=Leaked%20Secret%20Detected::" in a for a in annotations)
    # SAST annotation (::error)
    assert any("::error file=auth.py,line=1,title=SAST%20Security%20Vulnerability::" in a for a in annotations)
    # Mutant annotation (::warning)
    assert any("::warning file=auth.py,line=1,title=Surviving%20Mutation%20Test%20Gap::" in a for a in annotations)


def test_format_github_step_summary(tmp_path: Path):
    """Verify format_github_step_summary renders a complete Markdown dashboard."""
    sample_py = tmp_path / "service.py"
    sample_py.write_text("def run(): pass\n", encoding="utf-8")

    res = MutationResult(
        total_mutants=10,
        killed_mutants=9,
        survived_mutants=[],
        untested_files=[],
        runner_errors=[],
        skipped_constructs=[],
        mutation_score=90.0,
        duration_seconds=2.5,
        files_tested=[sample_py],
    )

    md = format_github_step_summary(res, [sample_py], repo_root=tmp_path, threshold=80.0)
    assert "DeployProof Verification" in md and "PASSED" in md
    assert "Mutation Testing" in md and "90.0%" in md
    assert "OWASP Top 10 SAST" in md and "CLEAN" in md
    assert "Secrets & Credentials" in md and "CLEAN" in md


def test_write_github_step_summary(tmp_path: Path, monkeypatch):
    """Verify write_github_step_summary_if_enabled writes markdown to $GITHUB_STEP_SUMMARY."""
    summary_file = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

    success = write_github_step_summary_if_enabled("# Sample Summary Header\n")
    assert success is True
    assert summary_file.is_file()
    assert "# Sample Summary Header" in summary_file.read_text(encoding="utf-8")


def test_cli_github_actions_flag(tmp_path: Path, monkeypatch, capsys):
    """Verify deployproof check --github-actions emits annotations and writes step summary."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    target_py = src_dir / "calc.py"
    target_py.write_text("def add(a, b): return a + b\n", encoding="utf-8")

    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    test_py = test_dir / "test_calc.py"
    test_py.write_text("from src.calc import add\ndef test_add(): assert add(1, 2) == 3\n", encoding="utf-8")

    summary_file = tmp_path / "ci_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    monkeypatch.chdir(tmp_path)

    from deployproof.cli import main
    res_code = main(["check", "--files", str(target_py), "--github-actions"])

    captured = capsys.readouterr()
    assert summary_file.is_file()
    assert "DeployProof Verification" in summary_file.read_text(encoding="utf-8")


def test_pre_commit_hooks_yaml():
    """Verify .pre-commit-hooks.yaml exists and defines standard hook IDs."""
    import yaml
    root = Path(__file__).resolve().parent.parent
    hooks_file = root / ".pre-commit-hooks.yaml"
    assert hooks_file.is_file()

    data = yaml.safe_load(hooks_file.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    hook_ids = [h.get("id") for h in data]
    assert "deployproof" in hook_ids
    assert "deployproof-check" in hook_ids
    assert "deployproof-full" in hook_ids
