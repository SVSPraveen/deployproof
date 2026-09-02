import os
import sys
import tempfile
from pathlib import Path
import pytest

from deployproof.symlinks import scan_session_files_for_symlinks, inspect_symlink, is_symlink_path
from deployproof.diff import get_uncommitted_session_files


def test_symlink_escape_absolute_path(tmp_path):
    """Test detection of absolute path symlink escape (e.g., /etc/passwd)."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    
    link_path = repo_root / "escape_abs.txt"
    # On systems supporting symlinks or git pointer
    raw_target = "/etc/passwd"
    
    try:
        os.symlink(raw_target, link_path)
    except (OSError, NotImplementedError):
        # Windows non-admin fallback for testing inspect_symlink
        pass

    finding = inspect_symlink(link_path, raw_target, repo_root)
    assert finding.is_escape is True
    assert "CWE-61" in finding.description or "sandbox escape" in finding.description


def test_symlink_escape_relative_traversal(tmp_path):
    """Test detection of relative path traversal symlink (e.g., ../../../etc/passwd)."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    
    link_path = repo_root / "escape_rel.py"
    raw_target = "../../../etc/passwd"
    
    finding = inspect_symlink(link_path, raw_target, repo_root)
    assert finding.is_escape is True


def test_symlink_escape_non_python_extension(tmp_path):
    """Test detection on non-python file extensions (.txt, .json, .env)."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    
    link_path = repo_root / "secret.env"
    raw_target = "/var/secrets/key.pem"
    
    finding = inspect_symlink(link_path, raw_target, repo_root)
    assert finding.is_escape is True
