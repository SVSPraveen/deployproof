"""
Test suite for Git History Secret Scanner.
"""

import subprocess
from pathlib import Path
import pytest

from deployproof.history_secrets import scan_git_history_for_secrets


def test_git_history_leaked_secret_detection(tmp_path: Path):
    """Verify detection of secret committed in past commit and deleted later."""
    repo = tmp_path / "leaky_repo"
    repo.mkdir()

    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test Committer"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "committer@test.com"], cwd=repo, capture_output=True, check=True)

    # Commit 1: Introduce secret in past commit
    sec_file = repo / "config.py"
    sec_file.write_text('OPENAI_API_KEY = "sk-proj-superSecretHistoricalKey1234567890ABCDEF"\n', encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Add old credentials"], cwd=repo, capture_output=True, check=True)

    # Commit 2: Delete the file (now clean in working directory)
    sec_file.unlink()
    dummy_file = repo / "clean.py"
    dummy_file.write_text("print('clean')\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Remove credentials"], cwd=repo, capture_output=True, check=True)

    # Scan history
    res = scan_git_history_for_secrets(repo, max_commits=10)
    assert res.clean is False
    assert len(res.findings) >= 1

    finding = res.findings[0]
    assert finding.rule_name == "OpenAI / Anthropic API Key"
    assert "sk" in finding.redacted_value
    assert finding.author == "Test Committer"
    assert finding.file_path == "config.py"


def test_git_history_clean_repo(tmp_path: Path):
    """Verify clean git history produces zero findings."""
    repo = tmp_path / "clean_repo"
    repo.mkdir()

    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Clean Committer"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "clean@test.com"], cwd=repo, capture_output=True, check=True)

    f = repo / "app.py"
    f.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial clean commit"], cwd=repo, capture_output=True, check=True)

    res = scan_git_history_for_secrets(repo, max_commits=10)
    assert res.clean is True
    assert len(res.findings) == 0
