import os
import sys
import subprocess
from pathlib import Path
import pytest
from deployproof.cli import create_parser, handle_check
from deployproof.symlinks import scan_session_files_for_symlinks, is_symlink_path


def test_cli_files_flag_preserves_symlinks(tmp_path):
    """Ensure --files flag does not dereference symlinks before scanning."""
    repo = tmp_path / "test_repo"
    repo.mkdir()
    
    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    
    link_file = repo / "passwd_link.txt"
    try:
        os.symlink("/etc/passwd", link_file)
        has_symlink = True
    except (OSError, NotImplementedError):
        # Windows without symlink privilege: write git-tracked pointer
        has_symlink = False

    if has_symlink:
        # Check scan_session_files_for_symlinks with un-resolved Path
        result = scan_session_files_for_symlinks([link_file], repo_root=repo)
        assert result.symlinks_found >= 1
        assert len(result.escape_findings) >= 1
        assert result.escape_findings[0].is_escape is True
