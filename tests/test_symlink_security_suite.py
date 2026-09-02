import os
import sys
import subprocess
from pathlib import Path
import pytest

from deployproof.symlinks import scan_session_files_for_symlinks, inspect_symlink, is_symlink_path, get_git_symlink_paths
from deployproof.diff import get_uncommitted_session_files, resolve_changed_session_files
from deployproof.cli import create_parser, handle_check


def test_symlink_escape_three_ways(tmp_path):
    """
    Directly verify the three researcher cases:
    1. A symlink pointing to /etc/passwd (absolute path, outside repo root)
    2. A relative-path traversal symlink (../../../etc/passwd)
    3. A different file extension (.txt instead of .py)
    """
    repo = tmp_path / "researcher_repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)

    # 1. Absolute path symlink (/etc/passwd)
    link1 = repo / "abs_escape.py"
    # 2. Relative traversal symlink (../../../etc/passwd)
    link2 = repo / "rel_escape.py"
    # 3. Non-python file extension (.txt)
    link3 = repo / "text_escape.txt"

    # Test inspect_symlink directly
    f1 = inspect_symlink(link1, "/etc/passwd", repo)
    assert f1.is_escape is True, "Case 1 failed: /etc/passwd not detected as escape"

    f2 = inspect_symlink(link2, "../../../etc/passwd", repo)
    assert f2.is_escape is True, "Case 2 failed: relative traversal not detected as escape"

    f3 = inspect_symlink(link3, "/etc/shadow", repo)
    assert f3.is_escape is True, "Case 3 failed: non-python extension not detected as escape"

    # Test scan_session_files_for_symlinks
    try:
        os.symlink("/etc/passwd", link1)
        os.symlink("../../../etc/passwd", link2)
        os.symlink("/etc/shadow", link3)
        has_symlink_support = True
    except (OSError, NotImplementedError):
        has_symlink_support = False

    if has_symlink_support:
        result = scan_session_files_for_symlinks([link1, link2, link3], repo_root=repo)
        assert result.symlinks_found == 3
        assert len(result.escape_findings) == 3
        for finding in result.escape_findings:
            assert finding.is_escape is True
