"""Unit tests for AST-based mock introduction detection."""

import subprocess
import tempfile
from pathlib import Path

import pytest

from deployproof.cli import main
from deployproof.mocks import (
    MockDetector,
    scan_session_files_for_mocks,
    scan_test_file_for_mocks,
)
from deployproof.reporter import format_report
from deployproof.mutator import MutationResult


def test_mock_detector_ast_patterns():
    """Verify AST visitor detects various mock imports, decorators, and calls."""
    code = """
import unittest
from unittest.mock import patch, MagicMock, Mock, AsyncMock
from unittest import mock
import pytest

@patch("db.connection.get_db")
def test_db_read(mock_get_db):
    mock_get_db.return_value = MagicMock(name="mock_session")
    assert True

def test_user_service(mocker):
    stub = mocker.patch("services.user.get_user", return_value={"id": 1})
    mock_obj = Mock()
    assert True

def test_api_auth(monkeypatch):
    monkeypatch.setattr("auth.verify_token", lambda token: True)
    monkeypatch.setenv("ENV", "test")
    assert True
"""
    lines = code.splitlines()
    tree = compile(code, "<test>", "exec", 0x400)  # ast.parse
    import ast
    tree = ast.parse(code)
    detector = MockDetector(Path("tests/test_sample.py"), lines)
    detector.visit(tree)

    assert len(detector.findings) > 0
    types = [f.mock_type for f in detector.findings]
    assert "mock_import" in types
    assert "patch_decorator" in types
    assert "mocker_fixture" in types
    assert "mocker_call" in types
    assert "monkeypatch_fixture" in types
    assert "monkeypatch_call" in types
    assert "mock_instantiation" in types


def test_diff_scoping_filters_preexisting_mocks(tmp_path: Path):
    """Verify pre-existing mocks in unchanged lines are not flagged."""
    test_file = tmp_path / "test_service.py"
    test_file.write_text(
        "import unittest.mock\n"
        "def test_old(monkeypatch):\n"
        "    monkeypatch.setattr('os.getcwd', lambda: '/tmp')\n"
        "    assert True\n"
        "def test_new():\n"
        "    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )

    # Scoped to only lines 5 and 6 (the new test without mocks)
    findings = scan_test_file_for_mocks(test_file)
    # Without root/diff, all lines are scanned
    assert len(findings) == 3

    # Now with line-scoping simulating git diff modifying only lines 5 and 6
    detector = MockDetector(
        test_file,
        test_file.read_text(encoding="utf-8").splitlines(),
        modified_lines={5, 6},
    )
    import ast
    detector.visit(ast.parse(test_file.read_text(encoding="utf-8")))
    assert len(detector.findings) == 0


def test_reporter_formatting_with_mocks():
    """Verify format_report displays the Mock Usage Introduced section."""
    test_file = Path("tests/test_db.py")
    detector = MockDetector(
        test_file,
        ["from unittest.mock import patch", "monkeypatch.setattr('db.run', lambda: 1)"],
    )
    import ast
    detector.visit(ast.parse("from unittest.mock import patch\nmonkeypatch.setattr('db.run', lambda: 1)"))

    from deployproof.mocks import MockScanSummary
    mock_summary = MockScanSummary(
        total_findings=len(detector.findings),
        findings=detector.findings,
        files_scanned=[test_file],
    )

    mut_res = MutationResult(total_mutants=0, killed_mutants=0)
    report = format_report(
        result=mut_res,
        target_files=[],
        mock_result=mock_summary,
        strict_mocks=False,
    )

    assert "Mock Usage Introduced (flagged for review):" in report
    assert "[*] Notice: 2 newly added mock/stub usages detected:" in report
    assert "test_db.py:1 [mock_import]" in report

    # Test with strict_mocks=True
    strict_report = format_report(
        result=mut_res,
        target_files=[],
        mock_result=mock_summary,
        strict_mocks=True,
    )
    assert "[!] STRICT GATE TRIGGERED:" in strict_report
    assert "Pre-check FAILED: 2 newly introduced mock(s) detected (--strict-mocks active)." in strict_report


def test_mock_detector_database_broken_impl_scenario(tmp_path: Path, capsys):
    """
    Test scenario:
    Source file 'db_service.py' has a broken implementation (returns None).
    Test file 'test_db_service.py' introduces a mock for the database call,
    so tests pass and mutation testing sees tests 'passing',
    BUT DeployProof flags the newly introduced mock usage for review.
    """
    # 1. Initialize git repo
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)

    # 2. Broken source file
    src_file = tmp_path / "db_service.py"
    src_file.write_text(
        "def query_user_name(user_id: int) -> str:\n"
        "    # Broken implementation: real DB not called, returns None\n"
        "    return None\n",
        encoding="utf-8",
    )

    # 3. Test file using unittest.mock to mask the broken DB implementation
    test_file = tmp_path / "test_db_service.py"
    test_file.write_text(
        "from unittest.mock import patch\n"
        "import db_service\n"
        "\n"
        "@patch('db_service.query_user_name', return_value='Alice')\n"
        "def test_query_user_name(mock_query):\n"
        "    assert mock_query(1) == 'Alice'\n",
        encoding="utf-8",
    )

    import os
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        # Default run: Informational warning, exit code 0
        exit_code_default = main(["check", "--files", str(src_file), str(test_file)])
        captured_default = capsys.readouterr()

        assert "Mock Usage Introduced (flagged for review):" in captured_default.out
        assert "Import from unittest.mock" in captured_default.out or "mock_import" in captured_default.out
        assert "@patch decorator" in captured_default.out
        # Exit code is 0 (informational, not blocking by default)
        assert exit_code_default == 0

        # Strict run: Fails gate when --strict-mocks is passed
        exit_code_strict = main(["check", "--files", str(src_file), str(test_file), "--strict-mocks"])
        captured_strict = capsys.readouterr()

        assert "[!] STRICT GATE TRIGGERED:" in captured_strict.out
        assert exit_code_strict == 1
    finally:
        os.chdir(orig_cwd)
