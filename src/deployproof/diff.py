"""Git diff-scoping resolver for DeployProof."""

import os
import subprocess
from pathlib import Path
from typing import List, Optional, Set

IGNORED_DIRS = {
    ".venv",
    "venv",
    "node_modules",
    "build",
    "dist",
    ".tox",
    ".mutmut-cache",
    "scratch_repos",
    "scratch",
    "stress_fixtures",
    "Test purpose",
    "fixtures",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "docs",
    "doc",
    ".github",
}


def is_ignored_path(path: Path, root: Path) -> bool:
    """
    Check if a path is located inside an ignored directory.
    
    Checks directory ancestor components relative to root only (never the filename itself),
    ensuring files like .env or files inside a legitimate 'env' package (e.g. env/game_env.py)
    are NOT skipped.
    """
    try:
        p_res = path.resolve()
        r_res = root.resolve()
        rel_parent = p_res.relative_to(r_res).parent
        parent_parts = set(rel_parent.parts)
    except ValueError:
        parent_parts = set()

    if parent_parts.intersection(IGNORED_DIRS):
        return True

    # Check for custom virtualenv directories named 'env' or '.env'
    for part in parent_parts:
        if part in {"env", ".env"}:
            try:
                idx = path.parts.index(part)
                dir_path = Path(*path.parts[:idx + 1])
                if (dir_path / "pyvenv.cfg").exists() or (dir_path / "bin" / "activate").exists() or (dir_path / "Scripts" / "activate.bat").exists():
                    return True
            except Exception:
                pass

    return False


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


def is_excluded_mutation_target(path: Path, root: Optional[Path] = None) -> bool:
    """
    Determine whether a Python file should be excluded from mutation testing.
    
    Excludes test files, documentation directories, Sphinx configs, setup.py,
    conftest files, and untargeted config files (*_config.py).
    """
    if is_test_file(path):
        return True

    name = path.name.lower()
    if name in {"setup.py", "conf.py"}:
        return True

    if root:
        try:
            rel_parts = [p.lower() for p in path.resolve().relative_to(root.resolve()).parent.parts]
        except ValueError:
            rel_parts = [p.lower() for p in path.parent.parts]
    else:
        rel_parts = [p.lower() for p in path.parent.parts]

    if any(p in {"docs", "doc", ".github", "demos", "examples", "benchmarks", "scratch", "stress_fixtures", "fixtures", "test purpose"} for p in rel_parts):
        return True

    if "scripts" in rel_parts or name.endswith("_config.py"):
        if root:
            from deployproof.mutator import discover_target_tests
            target_tests = discover_target_tests([path], root)
            if not target_tests:
                return True
        else:
            return True

    return False


def get_uncommitted_session_files(root: Path) -> Set[Path]:
    """Get uncommitted (staged, unstaged, untracked) files across all extensions."""
    files: Set[Path] = set()

    # 1. Check status for modified, staged, untracked files
    res = run_git(["status", "--porcelain", "-uall"], root)
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
                p = root / rel_path
                if p.is_file() or p.is_symlink() or os.path.islink(p):
                    files.add(p)
                elif p.is_dir():
                    for sub in p.rglob("*"):
                        if sub.is_file() or sub.is_symlink() or os.path.islink(sub):
                            files.add(sub)

    # 2. Check unstaged diff against HEAD (if commits exist)
    if has_commits(root):
        res_diff = run_git(["diff", "--name-only", "HEAD"], root)
        if res_diff.returncode == 0:
            for rel_path in res_diff.stdout.splitlines():
                rel_path = rel_path.strip().strip('"')
                if rel_path:
                    p = root / rel_path
                    if p.is_file() or p.is_symlink() or os.path.islink(p):
                        files.add(p)
                    elif p.is_dir():
                        for sub in p.rglob("*"):
                            if sub.is_file() or sub.is_symlink() or os.path.islink(sub):
                                files.add(sub)

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
                p = root / rel_path
                if p.is_file() or p.is_symlink() or os.path.islink(p):
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
                p = root / rel_path
                if p.is_file() or p.is_symlink() or os.path.islink(p):
                    files.add(p)

    # Include untracked files
    res_status = run_git(["status", "--porcelain", "-uall"], root)
    if res_status.returncode == 0:
        for line in res_status.stdout.splitlines():
            line = line.strip()
            if line.startswith("??"):
                parts = line.split(maxsplit=1)
                if len(parts) == 2:
                    rel_path = parts[1].strip().strip('"')
                    p = root / rel_path
                    if p.is_file() or p.is_symlink() or os.path.islink(p):
                        files.add(p)
                    elif p.is_dir():
                        for sub in p.rglob("*"):
                            if sub.is_file() or sub.is_symlink() or os.path.islink(sub):
                                files.add(sub)

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
        if is_ignored_path(p, root):
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
    
    Excludes virtualenvs, build directories, documentation, setup.py, and test files (unless include_tests=True).
    Returns sorted list of absolute Paths.
    """
    all_session_files = resolve_changed_session_files(cwd=cwd, base=base)
    py_files = [p for p in all_session_files if p.suffix == ".py"]

    if not include_tests:
        target_dir = (cwd or Path.cwd()).resolve()
        try:
            root = get_git_root(target_dir)
        except DiffScopeError:
            root = target_dir
        py_files = [p for p in py_files if not is_excluded_mutation_target(p, root)]

    return sorted(py_files)


def get_modified_line_ranges(
    file_path: Path,
    root: Path,
    base: Optional[str] = None,
) -> Optional[Set[int]]:
    """
    Get the set of line numbers (1-indexed) in file_path that were added or modified in the current diff.
    
    Returns None if the file is newly untracked, newly added, or if diffing fails (meaning all lines are new).
    """
    try:
        rel_path = file_path.relative_to(root).as_posix()
    except ValueError:
        rel_path = str(file_path)

    if not is_git_repo(root) or not has_commits(root):
        return None

    # Check if file is untracked or newly added
    res_status = run_git(["status", "--porcelain", "--", rel_path], root)
    if res_status.returncode == 0:
        stdout_s = res_status.stdout.strip()
        if stdout_s.startswith("??") or stdout_s.startswith("A ") or stdout_s.startswith("AM"):
            return None

    args = ["diff", "-U0"]
    if base:
        args.append(base)
    else:
        args.append("HEAD")
    args.extend(["--", rel_path])

    res = run_git(args, root)
    if res.returncode != 0:
        return None

    import re
    # Match @@ -old_start[,old_count] +new_start[,new_count] @@
    hunk_pattern = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
    modified_lines: Set[int] = set()
    for line in res.stdout.splitlines():
        m = hunk_pattern.match(line)
        if m:
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) is not None else 1
            for l in range(start, start + count):
                modified_lines.add(l)

    if not modified_lines:
        return None

    return modified_lines


def resolve_full_repo_session_files(cwd: Optional[Path] = None) -> List[Path]:
    """
    Resolve all non-ignored files across the repository for full-repo verification (--full-repo).
    Respects .gitignore via git ls-files if inside a git repository, or walks tree filtering IGNORED_DIRS.
    """
    target_dir = (cwd or Path.cwd()).resolve()
    if is_git_repo(target_dir):
        root = get_git_root(target_dir)
        res = run_git(["ls-files", "-c", "-o", "--exclude-standard"], root)
        if res.returncode == 0:
            files: List[Path] = []
            for line in res.stdout.splitlines():
                rel_path = line.strip().strip('"')
                if not rel_path:
                    continue
                p = (root / rel_path).resolve()
                if not (p.is_file() or p.is_symlink() or os.path.islink(p)):
                    continue
                if target_dir != root:
                    try:
                        p.relative_to(target_dir)
                    except ValueError:
                        continue
                    if is_ignored_path(p, target_dir):
                        continue
                else:
                    if is_ignored_path(p, root):
                        continue
                files.append(p)
            return sorted(files)

    # Fallback if not git repo or git command failed
    try:
        root = get_git_root(target_dir)
    except DiffScopeError:
        root = target_dir

    files = []
    for p in target_dir.rglob("*"):
        if p.is_file() or p.is_symlink() or os.path.islink(p):
            if is_ignored_path(p, target_dir):
                continue
            files.append(p.resolve())
    return sorted(files)




