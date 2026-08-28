"""Tests for DeployProof WSL delegation and fallback handling."""

from pathlib import Path
from unittest.mock import patch
import pytest

from deployproof.cli import main
from deployproof.wsl import (
    check_wsl_readiness,
    get_wsl_path,
    is_wsl_available,
    is_wsl_venv_configured,
    run_wsl_mutmut,
)


def test_wsl_readiness_on_non_windows():
    """Verify non-Windows platforms report WSL not applicable."""
    with patch("deployproof.wsl.is_windows", return_value=False):
        ready, msg = check_wsl_readiness()
        assert ready is False
        assert "Host is not Windows" in msg


def test_wsl_readiness_when_wsl_not_installed():
    """Verify clean fallback notice when WSL is not installed."""
    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("deployproof.wsl.is_wsl_available", return_value=False):
        ready, msg = check_wsl_readiness()
        assert ready is False
        assert "WSL (Windows Subsystem for Linux) not detected" in msg


def test_wsl_readiness_when_venv_missing():
    """Verify actionable notice when WSL is present but Linux venv is missing."""
    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("deployproof.wsl.is_wsl_available", return_value=True), \
         patch("deployproof.wsl.is_wsl_venv_configured", return_value=False):
        ready, msg = check_wsl_readiness()
        assert ready is False
        assert "~/.deployproof-wsl-venv" in msg
        assert "pip install mutmut" in msg


def test_wsl_readiness_when_configured():
    """Verify ready status when WSL and venv are present."""
    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("deployproof.wsl.is_wsl_available", return_value=True), \
         patch("deployproof.wsl.is_wsl_venv_configured", return_value=True):
        ready, msg = check_wsl_readiness()
        assert ready is True
        assert "configured" in msg


def test_cli_wsl_fallback_execution(capsys, tmp_path):
    """Verify CLI --wsl flag degrades gracefully to Tier 1 when venv is unconfigured."""
    src = tmp_path / "sample.py"
    src.write_text("def sub(a, b): return a - b\n", encoding="utf-8")
    test = tmp_path / "test_sample.py"
    test.write_text("from sample import sub\ndef test_sub(): assert sub(5, 2) == 3\n", encoding="utf-8")

    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("deployproof.wsl.is_wsl_available", return_value=True), \
         patch("deployproof.wsl.is_wsl_venv_configured", return_value=False):
        
        exit_code = main(["check", "--files", str(src), "--tests", str(test), "--wsl"])
        assert exit_code == 0
        captured = capsys.readouterr()
        # Verifies fallback notice was printed
        assert "WSL environment detected, but Linux Python environment" in captured.out
        # Verifies Tier 1 ran successfully
        assert "LOCAL PRE-CHECK" in captured.out
        assert "100.0%" in captured.out


def test_get_wsl_path_translation():
    """Verify Windows to WSL path translation via wslpath."""
    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("subprocess.run") as mock_sub:
        mock_sub.return_value.returncode = 0
        mock_sub.return_value.stdout = "/mnt/c/project\n"
        
        p = get_wsl_path(Path("C:/project"))
        assert p == "/mnt/c/project"
