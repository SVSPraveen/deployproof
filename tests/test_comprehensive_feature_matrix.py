import json
import os
import subprocess
import time
from pathlib import Path
import pytest

from deployproof.cli import create_parser, handle_check
from deployproof.dependencies import extract_all_new_dependencies
from deployproof.diff import get_diff_against_base_session_files, resolve_changed_session_files
from deployproof.mutator import run_mutation_tests


def test_base_ref_diffing(tmp_path):
    """Verify --base <ref> diffs accurately against an earlier commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, capture_output=True, check=True)

    # Initial commit (v1.0)
    file_a = repo / "file_a.py"
    file_a.write_text("def fn_a():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo, capture_output=True, check=True)
    
    # Tag base
    subprocess.run(["git", "tag", "v1.0"], cwd=repo, capture_output=True, check=True)

    # Second commit (v2.0 adds file_b)
    file_b = repo / "file_b.py"
    file_b.write_text("def fn_b():\n    return 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Add file_b"], cwd=repo, capture_output=True, check=True)

    # Diff against base v1.0
    changed_files = get_diff_against_base_session_files(repo, "v1.0")
    assert any(f.name == "file_b.py" for f in changed_files)
    assert not any(f.name == "file_a.py" for f in changed_files)


def test_timeout_stops_hanging_test(tmp_path):
    """Verify test_runner_timeout terminates a hanging mutant and marks it as killed.

    The implementation uses effective_timeout = max(baseline_duration * 1.5, test_runner_timeout),
    so the wall-clock bound must account for baseline overhead on a cold tmp_path.
    We verify:
      (a) the run terminates at all (doesn't hang indefinitely), and
      (b) the mutant is classified as 'killed' (timeout counts as a kill), and
      (c) the mutation score is 100% (only 1 mutant, killed by timeout).
    """
    target = tmp_path / "hang_service.py"
    target.write_text("def compute():\n    return 1\n", encoding="utf-8")

    test_file = tmp_path / "test_hang.py"
    # When mutant changes return 1 to None/0, loops forever
    test_file.write_text(
        "import time\nfrom hang_service import compute\ndef test_compute():\n    while compute() != 1:\n        time.sleep(0.1)\n",
        encoding="utf-8",
    )

    t0 = time.time()
    res = run_mutation_tests(
        target_files=[target],
        repo_root=tmp_path,
        extra_pytest_args=[str(test_file)],
        test_runner_timeout=1.0,  # 1-second configured timeout
    )
    dt = time.time() - t0

    # (a) Must terminate — effective_timeout = max(baseline*1.5, 1.0).
    #     Baseline on a cold tmp_path is typically 3-5s on Windows, so
    #     effective_timeout ≈ 5-7s. Total wall time should be under 30s.
    assert dt < 30.0, f"Run took {dt:.1f}s — something hung beyond effective_timeout"

    # (b) The hanging mutants must be treated as killed (timeout = kill).
    assert res.killed_mutants == res.total_mutants, (
        f"Expected all mutants killed, got {res.killed_mutants} killed / "
        f"{len(res.survived_mutants)} survived"
    )
    assert len(res.survived_mutants) == 0, "Timeout-killed mutant should not appear as survived"

    # (c) Score should be 100% (all killed).
    assert res.mutation_score == 100.0


def test_recursive_requirements_and_dynamic_imports(tmp_path):
    """Verify recursive -r requirements includes and dynamic importlib imports."""
    base_req = tmp_path / "requirements.txt"
    sub_req = tmp_path / "requirements-dev.txt"
    
    sub_req.write_text("pytest-cov>=4.0.0\n", encoding="utf-8")
    base_req.write_text("-r requirements-dev.txt\nrequests>=2.28.0\n", encoding="utf-8")

    code_file = tmp_path / "dynamic_loader.py"
    code_file.write_text(
        "import importlib\nmod = importlib.import_module('fake_dynamic_pkg')\nobj = __import__('another_dynamic_pkg')\n",
        encoding="utf-8",
    )

    deps = extract_all_new_dependencies([base_req, code_file], root=tmp_path, full_repo=True)
    names = {d.name for d in deps}
    assert "requests" in names
    assert "pytest-cov" in names
    assert "fake-dynamic-pkg" in names or "fake_dynamic_pkg" in names
    assert "another-dynamic-pkg" in names or "another_dynamic_pkg" in names


def test_git_pre_push_hook_blocks_leak(tmp_path):
    """Verify git pre-push hook fails with returncode 1 when dirty code / secret is introduced."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, capture_output=True, check=True)

    # Initial clean commit
    f = repo / "clean.py"
    f.write_text("print('clean')\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Clean"], cwd=repo, capture_output=True, check=True)

    # Create .env with secret
    secret_env = repo / ".env"
    secret_env.write_text("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n", encoding="utf-8")

    # Run CLI check
    parser = create_parser()
    args = parser.parse_args(["check", "--json"])
    
    # Run in the repo directory
    orig_cwd = os.getcwd()
    try:
        os.chdir(repo)
        exit_code = handle_check(args)
        # Gate must return 1 to block git push!
        assert exit_code == 1
    finally:
        os.chdir(orig_cwd)
