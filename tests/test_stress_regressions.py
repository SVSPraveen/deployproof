"""Regression tests for large-repo stress findings (zero-test handling, utf-8 encoding, relative paths)."""

import subprocess
import tempfile
from pathlib import Path
import pytest

from deployproof.cli import main
from deployproof.diff import get_git_root, resolve_changed_python_files, resolve_changed_session_files
from deployproof.mutator import run_mutation_tests


def test_zero_matching_tests_scenario(tmp_path, monkeypatch):
    """
    CRITICAL REGRESSION: A file with zero matching tests (pytest exit code 5)
    must NEVER report a passing score. It must report 0.0% score, mark mutants as
    SURVIVED, populate untested_files, and return exit code 1.
    """
    monkeypatch.chdir(tmp_path)
    untested_src = tmp_path / "orphan_service.py"
    untested_src.write_text("def compute(x: int) -> int:\n    return x * 10\n", encoding="utf-8")

    # An empty test file or non-matching test
    empty_test = tmp_path / "test_unrelated.py"
    empty_test.write_text("# No tests here\n", encoding="utf-8")

    res = run_mutation_tests(
        target_files=[untested_src],
        repo_root=tmp_path,
        extra_pytest_args=[str(empty_test)],
    )

    # Must NOT report 100% killed!
    assert res.killed_mutants == 0
    assert len(res.survived_mutants) == res.total_mutants
    assert res.mutation_score == 0.0
    assert untested_src in res.untested_files

    # CLI check should exit with code 1
    exit_code = main(["check", "--files", str(untested_src), "--tests", str(empty_test)])
    assert exit_code == 1


def test_utf8_emoji_commit_message(tmp_path):
    """
    Verify git diff resolution and subprocess execution handle UTF-8 / emojis
    in commit messages without crashing on Windows cp1252.
    """
    repo = tmp_path / "emoji_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Emoji Tester 🚀"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo, check=True)

    src = repo / "app.py"
    src.write_text("# Non-ASCII content: 日本語, Español, Ümlaut 🌟\ndef greet(): return 'hello'\n", encoding="utf-8")

    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "📝 Add app module with emojis 🚀 and non-ascii 日本語"],
        cwd=repo,
        check=True,
    )

    files = resolve_changed_python_files(cwd=repo)
    assert src in files


def test_nested_path_relative_ignore_check(tmp_path):
    """
    Verify that a repository located in a parent folder named 'env' or 'build'
    or 'scratch_repos' does NOT falsely ignore its internal files.
    """
    parent_dir = tmp_path / "scratch_repos" / "my_project"
    parent_dir.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=parent_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=parent_dir, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=parent_dir, check=True)

    src = parent_dir / "core.py"
    src.write_text("x = 100\n", encoding="utf-8")
    subprocess.run(["git", "add", "core.py"], cwd=parent_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=parent_dir, check=True)

    files = resolve_changed_python_files(cwd=parent_dir)
    assert src in files
