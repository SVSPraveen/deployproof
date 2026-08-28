"""Git diff-scoping resolver for DeployProof."""

import os
import subprocess
from pathlib import Path
from typing import List, Optional, Set

IGNORED_DIRS = {
    ".venv",
    "venv",
    ".env",
    "env",
    "node_modules",
    "build",
    "dist",
    ".tox",
    ".mutmut-cache",
    "scratch_repos",
    ".git",
    "__pycache__",
    ".pytest_cache",
}


class DiffScopeError(Exception):
    """Base exception for diff scoping errors."""
    pass


class NotAGitRepositoryError(DiffScopeError):
    """Raised when current working directory is not a git repository."""
    pass


class InvalidBaseRefError(DiffScopeError):
    """Raised when a specified base ref does not exist."""
    pass


def run_git(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a git command in the specified directory."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError:
        raise DiffScopeError("git executable not found in PATH.")


def is_git_repo(cwd: Path) -> bool:
    """Check if the directory is inside a git work tree."""
    res = run_git(["rev-parse", "--is-inside-work-tree"], cwd)
    return res.returncode == 0 and res.stdout.strip() == "true"


def get_git_root(cwd: Path) -> Path:
    """Get the root directory of the git repository."""
    if not is_git_repo(cwd):
        raise NotAGitRepositoryError("Not a git repository.")
    res = run_git(["rev-parse", "--show-toplevel"], cwd)
    if res.returncode != 0:
        raise NotAGitRepositoryError("Failed to determine git repository root.")
    return Path(res.stdout.strip()).resolve()


def verify_ref_exists(ref: str, cwd: Path) -> bool:
    """Check if a git ref exists."""
    res = run_git(["rev-parse", "--verify", "--quiet", ref], cwd)
    return res.returncode == 0


def has_commits(cwd: Path) -> bool:
    """Check if the repository has at least one commit."""
    res = run_git(["rev-parse", "--verify", "--quiet", "HEAD"], cwd)
    return res.returncode == 0


def is_test_file(path: Path) -> bool:
    """
    Determine whether a path is a test file or located within a test folder.
    
    Test files should be excluded from mutation targets (though they verify targets).
    """
    name = path.name.lower()
    if name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py":
        return True

    parts = [p.lower() for p in path.parts]
    if "tests" in parts or "test" in parts or "testing" in parts:
        return True
    return False


def get_uncommitted_session_files(root: Path) -> Set[Path]:
    """Get uncommitted (staged, unstaged, untracked) files across all extensions."""
    files: Set[Path] = set()

    # 1. Check status for modified, staged, untracked files
    res = run_git(["status", "--porcelain"], root)
    if res.returncode == 0:
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                status, rel_path = parts[0], parts[1]
                if "->" in rel_path:
                    rel_path = rel_path.split("->")[-1].strip()
                rel_path = rel_path.strip('"')
                p = (root / rel_path).resolve()
                if p.is_file():
                    files.add(p)

    # 2. Check unstaged diff against HEAD (if commits exist)
    if has_commits(root):
        res_diff = run_git(["diff", "--name-only", "HEAD"], root)
        if res_diff.returncode == 0:
            for rel_path in res_diff.stdout.splitlines():
                rel_path = rel_path.strip().strip('"')
                if rel_path:
                    p = (root / rel_path).resolve()
                    if p.is_file():
                        files.add(p)

    return files


def get_latest_commit_session_files(root: Path) -> Set[Path]:
    """Get all files changed in the most recent commit (HEAD)."""
    files: Set[Path] = set()
    if not has_commits(root):
        return files

    res = run_git(["diff-tree", "--no-commit-id", "--name-only", "-r", "--root", "HEAD"], root)
    if res.returncode == 0:
        for rel_path in res.stdout.splitlines():
            rel_path = rel_path.strip().strip('"')
            if rel_path:
                p = (root / rel_path).resolve()
                if p.is_file():
                    files.add(p)
    return files


def get_diff_against_base_session_files(root: Path, base: str) -> Set[Path]:
    """Get files changed between base ref and working tree / HEAD."""
    if not verify_ref_exists(base, root):
        raise InvalidBaseRefError(f"Git reference '{base}' does not exist.")

    files: Set[Path] = set()

    # Diff base against working tree
    res = run_git(["diff", "--name-only", base], root)
    if res.returncode == 0:
        for rel_path in res.stdout.splitlines():
            rel_path = rel_path.strip().strip('"')
            if rel_path:
                p = (root / rel_path).resolve()
                if p.is_file():
                    files.add(p)

    # Include untracked files
    res_status = run_git(["status", "--porcelain"], root)
    if res_status.returncode == 0:
        for line in res_status.stdout.splitlines():
            line = line.strip()
            if line.startswith("??"):
                parts = line.split(maxsplit=1)
                if len(parts) == 2:
                    rel_path = parts[1].strip().strip('"')
                    p = (root / rel_path).resolve()
                    if p.is_file():
                        files.add(p)

    return files


def resolve_changed_session_files(
    cwd: Optional[Path] = None,
    base: Optional[str] = None,
) -> List[Path]:
    """
    Resolve list of all changed session files (any extension) for secret scanning and general scoping.
    """
    target_dir = (cwd or Path.cwd()).resolve()
    root = get_git_root(target_dir)

    if base:
        changed = get_diff_against_base_session_files(root, base)
    else:
        # Step 1: Check working-tree uncommitted changes
        changed = get_uncommitted_session_files(root)
        # Step 2: If clean, check latest commit
        if not changed:
            changed = get_latest_commit_session_files(root)

    filtered: List[Path] = []
    for p in changed:
        try:
            rel_parts = set(p.relative_to(root).parts)
        except ValueError:
            rel_parts = set(p.parts)
        if rel_parts.intersection(IGNORED_DIRS):
            continue
        filtered.append(p)

    return sorted(filtered)


def resolve_changed_python_files(
    cwd: Optional[Path] = None,
    base: Optional[str] = None,
    include_tests: bool = False,
) -> List[Path]:
    """
    Resolve list of changed Python files based on the Smart Session Cascade or --base flag.
    
    Excludes virtualenvs, build directories, and test files (unless include_tests=True).
    Returns sorted list of absolute Paths.
    """
    all_session_files = resolve_changed_session_files(cwd=cwd, base=base)
    py_files = [p for p in all_session_files if p.suffix == ".py"]

    if not include_tests:
        py_files = [p for p in py_files if not is_test_file(p)]

    return sorted(py_files)
