"""Tests for git diff resolution in DeployProof."""

import subprocess
import tempfile
from pathlib import Path
import pytest

from deployproof.diff import (
    DiffScopeError,
    InvalidBaseRefError,
    NotAGitRepositoryError,
    get_git_root,
    resolve_changed_python_files,
)


@pytest.fixture
def temp_git_repo():
    """Create a temporary git repository."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
        yield root


def test_not_a_git_repo():
    """Verify NotAGitRepositoryError when running outside a git repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        non_repo = Path(tmpdir).resolve()
        with pytest.raises(NotAGitRepositoryError):
            get_git_root(non_repo)


def test_empty_git_repo_clean(temp_git_repo):
    """Verify clean empty repo resolves to empty list without error."""
    files = resolve_changed_python_files(cwd=temp_git_repo)
    assert files == []


def test_untracked_python_files_detected(temp_git_repo):
    """Verify untracked .py files in working tree are detected."""
    sample = temp_git_repo / "new_module.py"
    sample.write_text("def hello(): return 1\n", encoding="utf-8")
    
    # Non-python file should be ignored
    readme = temp_git_repo / "README.md"
    readme.write_text("# Hello\n", encoding="utf-8")

    files = resolve_changed_python_files(cwd=temp_git_repo)
    assert sample in files
    assert readme not in files


def test_modified_and_staged_files_detected(temp_git_repo):
    """Verify modified and staged files are detected in working tree."""
    mod_file = temp_git_repo / "logic.py"
    mod_file.write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "logic.py"], cwd=temp_git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=temp_git_repo, check=True)

    # Modify file
    mod_file.write_text("x = 2\n", encoding="utf-8")
    files = resolve_changed_python_files(cwd=temp_git_repo)
    assert mod_file in files


def test_clean_working_tree_falls_back_to_latest_commit(temp_git_repo):
    """Verify clean tree checks latest commit."""
    file_a = temp_git_repo / "feature.py"
    file_a.write_text("def foo(): return True\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.py"], cwd=temp_git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "Add feature"], cwd=temp_git_repo, check=True)

    # Working tree is clean now
    files = resolve_changed_python_files(cwd=temp_git_repo)
    assert file_a in files


def test_invalid_base_ref(temp_git_repo):
    """Verify InvalidBaseRefError on invalid base reference."""
    file_a = temp_git_repo / "feature.py"
    file_a.write_text("def foo(): return True\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.py"], cwd=temp_git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "Add feature"], cwd=temp_git_repo, check=True)

    with pytest.raises(InvalidBaseRefError):
        resolve_changed_python_files(cwd=temp_git_repo, base="nonexistent_branch")


def test_test_files_excluded_from_mutation_targets(temp_git_repo):
    """Verify test files are excluded from mutation targets."""
    src_file = temp_git_repo / "app.py"
    src_file.write_text("def run(): pass\n", encoding="utf-8")
    
    test_dir = temp_git_repo / "tests"
    test_dir.mkdir()
    test_file = test_dir / "test_app.py"
    test_file.write_text("def test_run(): pass\n", encoding="utf-8")

    files = resolve_changed_python_files(cwd=temp_git_repo)
    assert src_file in files
    assert test_file not in files
