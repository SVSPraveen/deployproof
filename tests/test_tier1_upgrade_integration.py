"""
End-to-end integration test suite for the expanded Tier 1 scanner matrix:
- Statement Deletion Mutations
- AST SAST Security Analysis (OWASP Top 10)
- Git History Secret Scanner
- OSV Dependency Vulnerability Checker
- Unified Structured Output
"""

import json
import subprocess
from pathlib import Path
import pytest

from deployproof.cli import main, handle_check, create_parser
from deployproof.sast import scan_file_for_sast
from deployproof.history_secrets import scan_git_history_for_secrets
from deployproof.cve import scan_dependencies_for_cves
from deployproof.mutator import generate_mutants_for_file


def test_statement_mutation_generation_on_logic_constructs(tmp_path: Path):
    """Verify statement deletion mutations generate on functions with return, assert, and raise."""
    code_file = tmp_path / "validator.py"
    code_file.write_text("""def validate_user(user_id, is_active):
    assert user_id > 0, "User ID must be positive"
    if not is_active:
        raise PermissionError("Inactive user")
    return {"id": user_id, "status": "active"}
""", encoding="utf-8")

    mutants = generate_mutants_for_file(code_file)
    descriptions = [m.description for m in mutants]
    
    # Assert statement deletion
    assert any("Delete assert statement" in d for d in descriptions)
    # Raise statement deletion
    assert any("Delete raise statement" in d for d in descriptions)
    # Return statement mutation
    assert any("Replace return value with None" in d for d in descriptions)


def test_unified_cli_check_json_structure(tmp_path: Path, capsys):
    """Verify deployproof check --json outputs all security scanner results in unified schema."""
    repo = tmp_path / "sample_project"
    repo.mkdir()

    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, capture_output=True, check=True)

    src_file = repo / "core.py"
    src_file.write_text("""def compute(x: int) -> int:
    return x * 2
""", encoding="utf-8")

    test_file = repo / "test_core.py"
    test_file.write_text("""from core import compute

def test_compute():
    assert compute(5) == 10
    assert compute(0) == 0
""", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo, capture_output=True, check=True)

    parser = create_parser()
    args = parser.parse_args(["check", "--full-repo", "--json", "--files", str(src_file)])

    # Run check in the repo directory
    import os
    orig_cwd = os.getcwd()
    try:
        os.chdir(repo)
        code = handle_check(args)
    finally:
        os.chdir(orig_cwd)

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert "sast" in payload
    assert "git_history_secrets" in payload
    assert "cve_vulnerabilities" in payload
    assert "mutation_testing" in payload
    assert payload["sast"]["clean"] is True
    assert payload["git_history_secrets"]["clean"] is True
