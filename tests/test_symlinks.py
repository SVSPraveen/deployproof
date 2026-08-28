"""Tests for DeployProof symlink and sandbox-escape scanner (CWE-61 + CWE-451)."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from deployproof.cli import main
from deployproof.reporter import format_report
from deployproof.mutator import MutationResult
from deployproof.symlinks import (
    SymlinkFinding,
    SymlinkScanResult,
    inspect_symlink,
    is_symlink_path,
    scan_session_files_for_symlinks,
)


def test_in_repo_legitimate_symlink_detection():
    """Verify that legitimate in-repo symlinks are identified and marked as non-escaping."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        config_dir = root / "config"
        config_dir.mkdir()
        target_file = config_dir / "app.json"
        target_file.write_text('{"env": "local"}', encoding="utf-8")

        link_dir = root / "links"
        link_dir.mkdir()
        symlink_file = link_dir / "active_config.json"

        # Test inspection logic
        finding = inspect_symlink(
            symlink_path=symlink_file,
            raw_target="../config/app.json",
            repo_root=root,
        )

        assert finding.is_escape is False
        assert finding.resolved_target == target_file
        assert finding.target_exists is True
        assert "Safe in-repo" in finding.description


def test_ghostapproval_sandbox_escape_symlink_detection():
    """Verify that symlinks resolving outside repo root are flagged as critical escapes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        outside_dir = root.parent
        external_target = outside_dir / "sensitive_host_data.env"

        decoy_symlink = root / "decoy_settings.json"

        finding = inspect_symlink(
            symlink_path=decoy_symlink,
            raw_target="../sensitive_host_data.env",
            repo_root=root,
        )

        assert finding.is_escape is True
        assert finding.resolved_target == external_target.resolve()
        assert "CRITICAL: Symlink resolves outside" in finding.description
        assert "GhostApproval" in finding.description


def test_dangling_symlink_escape_detection():
    """Verify that non-existent / dangling external symlinks are flagged without crashing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        decoy_symlink = root / "broken_link.json"

        finding = inspect_symlink(
            symlink_path=decoy_symlink,
            raw_target="../../nonexistent_external_file_xyz_123.bin",
            repo_root=root,
        )

        assert finding.is_escape is True
        assert finding.target_exists is False
        assert "CRITICAL: Symlink resolves outside" in finding.description


def test_git_mode_120000_text_pointer_detection():
    """Verify that git mode 120000 pointer files on Windows are detected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        pointer_file = root / "pointer.txt"
        pointer_file.write_text("../../../etc/passwd", encoding="utf-8")

        git_symlinks = {pointer_file.resolve()}

        is_link, raw_target = is_symlink_path(pointer_file, git_symlinks=git_symlinks)
        assert is_link is True
        assert raw_target == "../../../etc/passwd"


def test_scan_session_files_for_symlinks():
    """Test full scan over multiple files with mixed safe and escaping symlinks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        local_target = root / "local.py"
        local_target.write_text("print('hello')", encoding="utf-8")

        safe_link = root / "safe_link.py"
        escape_link = root / "escape_link.py"
        normal_file = root / "normal.py"
        normal_file.write_text("x = 1", encoding="utf-8")

        # Mock is_symlink_path behavior
        def mock_is_symlink_path(p: Path, git_symlinks=None):
            if p == safe_link:
                return True, "local.py"
            elif p == escape_link:
                return True, "../outside.py"
            return False, ""

        with patch("deployproof.symlinks.is_symlink_path", side_effect=mock_is_symlink_path):
            result = scan_session_files_for_symlinks(
                files=[safe_link, escape_link, normal_file],
                repo_root=root,
            )

            assert result.files_scanned == 3
            assert result.symlinks_found == 2
            assert len(result.escape_findings) == 1
            assert len(result.safe_symlinks) == 1
            assert result.escape_findings[0].symlink_path == escape_link
            assert result.safe_symlinks[0].symlink_path == safe_link


def test_reporter_formatting_with_symlink_escape():
    """Verify that reporter formats symlink findings with apparent vs resolved paths."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        decoy = root / "auth_config.json"
        resolved = root.parent / "system_passwords.txt"

        finding = SymlinkFinding(
            symlink_path=decoy,
            link_target_raw="../system_passwords.txt",
            resolved_target=resolved,
            is_escape=True,
            description="CRITICAL: Symlink resolves outside the repository root directory (CWE-61/CWE-451).",
            target_exists=False,
        )

        symlink_result = SymlinkScanResult(
            files_scanned=2,
            symlinks_found=1,
            escape_findings=[finding],
            safe_symlinks=[],
            duration_seconds=0.01,
        )

        dummy_mut_res = MutationResult(
            total_mutants=0,
            killed_mutants=0,
            survived_mutants=[],
            untested_files=[],
            skipped_constructs=[],
            runner_errors=[],
            duration_seconds=0.01,
        )

        report = format_report(
            result=dummy_mut_res,
            target_files=[decoy],
            symlink_result=symlink_result,
            repo_root=root,
        )

        assert "Symlink & Sandbox Escape Scan (CWE-61/CWE-451):" in report
        assert "[!] 1 sandbox-escape symlink detected:" in report
        assert "auth_config.json -> ../system_passwords.txt" in report
        assert "Apparent Path:   auth_config.json" in report
        assert "Severity:        CRITICAL (Escapes repository sandbox)" in report
        assert "SECURITY ALERT: 1 symlink(s) escape repository sandbox" in report


def test_cli_blocks_when_symlink_escape_present(capsys):
    """Verify CLI check command returns exit code 1 when symlink escape is detected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        decoy = root / "service_decoy.json"
        decoy.write_text("{}", encoding="utf-8")

        def mock_scan(files, repo_root=None):
            return SymlinkScanResult(
                files_scanned=1,
                symlinks_found=1,
                escape_findings=[
                    SymlinkFinding(
                        symlink_path=decoy,
                        link_target_raw="../../secret.txt",
                        resolved_target=root.parent / "secret.txt",
                        is_escape=True,
                        description="Sandbox escape detected",
                    )
                ],
                safe_symlinks=[],
            )

        with patch("deployproof.cli.scan_session_files_for_symlinks", side_effect=mock_scan):
            exit_code = main(["check", "--files", str(decoy)])
            assert exit_code == 1

            captured = capsys.readouterr()
            assert "Symlink & Sandbox Escape Scan" in captured.out
            assert "sandbox-escape symlink" in captured.out
