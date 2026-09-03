"""Tests for DeployProof WSL delegation and fallback handling."""

import subprocess
from pathlib import Path
from unittest.mock import patch

from deployproof.cli import main
from deployproof.wsl import (
    DEFAULT_WSL_VENV,
    check_wsl_readiness,
    get_wsl_path,
    is_windows,
    is_wsl_available,
    is_wsl_venv_configured,
    run_wsl_mutmut,
)


def test_is_windows():
    """Verify is_windows checks system platform correctly."""
    with patch("platform.system", return_value="Windows"):
        assert is_windows() is True
    with patch("platform.system", return_value="Linux"):
        assert is_windows() is False
    with patch("platform.system", return_value="Darwin"):
        assert is_windows() is False


def test_is_wsl_available_branches():
    """Verify is_wsl_available under all platform and error branches."""
    # 1. Non-Windows
    with patch("deployproof.wsl.is_windows", return_value=False):
        assert is_wsl_available() is False

    # 2. Windows with WSL available (code 0)
    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        assert is_wsl_available() is True
        mock_run.assert_called_once_with(
            ["wsl", "--status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )

    # 3. Windows with WSL failing (non-zero)
    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        assert is_wsl_available() is False

    # 4. Windows with FileNotFoundError
    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("subprocess.run", side_effect=FileNotFoundError):
        assert is_wsl_available() is False

    # 5. Windows with SubprocessError
    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("subprocess.run", side_effect=subprocess.SubprocessError):
        assert is_wsl_available() is False


def test_default_wsl_venv():
    """Verify default WSL venv path constant."""
    assert DEFAULT_WSL_VENV == "~/.deployproof-wsl-venv"


def test_get_wsl_path_branches(tmp_path: Path):
    """Verify get_wsl_path conversions on Windows and non-Windows."""
    sample = tmp_path / "project" / "file.py"
    posix_expected = str(sample.resolve()).replace("\\", "/")

    # 1. Non-Windows
    with patch("deployproof.wsl.is_windows", return_value=False):
        res = get_wsl_path(sample)
        assert res == str(sample.resolve())

    # 2. Windows success
    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = " /mnt/c/project/file.py \n"
        assert get_wsl_path(sample) == "/mnt/c/project/file.py"
        mock_run.assert_called_once_with(
            ["wsl", "wslpath", "-u", posix_expected],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )

    # 3. Windows non-zero return code
    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        assert get_wsl_path(sample) is None

    # 4. Windows FileNotFoundError
    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("subprocess.run", side_effect=FileNotFoundError):
        assert get_wsl_path(sample) is None

    # 5. Windows SubprocessError
    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("subprocess.run", side_effect=subprocess.SubprocessError):
        assert get_wsl_path(sample) is None


def test_is_wsl_venv_configured_branches():
    """Verify is_wsl_venv_configured under all branches."""
    # 1. Non-Windows
    with patch("deployproof.wsl.is_windows", return_value=False):
        assert is_wsl_venv_configured() is False

    # 2. Windows with mutmut found (code 0)
    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        assert is_wsl_venv_configured("~/.my-venv") is True
        mock_run.assert_called_once_with(
            ["wsl", "bash", "-c", "test -f ~/.my-venv/bin/mutmut"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )

    # 3. Windows with mutmut missing (code 1)
    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        assert is_wsl_venv_configured() is False

    # 4. Windows FileNotFoundError
    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("subprocess.run", side_effect=FileNotFoundError):
        assert is_wsl_venv_configured() is False

    # 5. Windows SubprocessError
    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("subprocess.run", side_effect=subprocess.SubprocessError):
        assert is_wsl_venv_configured() is False


def test_wsl_readiness_on_non_windows():
    """Verify non-Windows platforms report WSL not applicable."""
    with patch("deployproof.wsl.is_windows", return_value=False):
        ready, msg = check_wsl_readiness()
        assert ready is False
        assert msg == "Host is not Windows; WSL delegation is only applicable on Windows."


def test_wsl_readiness_when_wsl_not_installed():
    """Verify clean fallback notice when WSL is not installed."""
    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("deployproof.wsl.is_wsl_available", return_value=False):
        ready, msg = check_wsl_readiness()
        assert ready is False
        assert msg == (
            "[!] WSL (Windows Subsystem for Linux) not detected.\n"
            "    To run verified mutation tests locally on Windows, install WSL (wsl --install),\n"
            "    or rely on Tier 1 pre-check locally and verify in GitHub Actions CI."
        )


def test_wsl_readiness_when_venv_missing():
    """Verify actionable notice when WSL is present but Linux venv is missing."""
    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("deployproof.wsl.is_wsl_available", return_value=True), \
         patch("deployproof.wsl.is_wsl_venv_configured", return_value=False):
        ready, msg = check_wsl_readiness(DEFAULT_WSL_VENV)
        assert ready is False
        assert msg == (
            f"[!] WSL environment detected, but Linux Python environment ({DEFAULT_WSL_VENV}) with mutmut was not found.\n"
            f"    To configure WSL for verified local testing:\n"
            f"      wsl bash -c \"python3 -m venv {DEFAULT_WSL_VENV} && {DEFAULT_WSL_VENV}/bin/pip install mutmut pytest\"\n"
            "    Running Tier 1 local pre-check instead. Full verified score will run in CI on push."
        )


def test_wsl_readiness_when_configured():
    """Verify ready status when WSL and venv are present."""
    with patch("deployproof.wsl.is_windows", return_value=True), \
         patch("deployproof.wsl.is_wsl_available", return_value=True), \
         patch("deployproof.wsl.is_wsl_venv_configured", return_value=True):
        ready, msg = check_wsl_readiness()
        assert ready is True
        assert msg == "WSL and mutmut environment configured."


def test_run_wsl_mutmut_path_failure(tmp_path: Path):
    """Verify run_wsl_mutmut fails gracefully when get_wsl_path fails."""
    with patch("deployproof.wsl.get_wsl_path", return_value=None):
        res = run_wsl_mutmut(tmp_path, [tmp_path / "app.py"])
        assert res["success"] is False
        assert res["error"] == "Failed to resolve WSL repository path."


def test_run_wsl_mutmut_success_and_failures(tmp_path: Path):
    """Verify run_wsl_mutmut handling of success, return codes, timeouts, and exceptions."""
    repo = tmp_path
    f1 = repo / "src" / "app.py"
    f2 = Path("/external/outside.py")  # will trigger ValueError on relative_to

    with patch("deployproof.wsl.get_wsl_path", return_value="/mnt/c/myrepo"), \
         patch("subprocess.run") as mock_run:
        
        # 1. Success execution
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "mutmut complete: 10 killed"
        mock_run.return_value.stderr = ""
        
        res = run_wsl_mutmut(repo, [f1, f2], venv_path="~/.custom-venv", timeout=60.0)
        assert res["success"] is True
        assert res["stdout"] == "mutmut complete: 10 killed"
        assert res["returncode"] == 0
        mock_run.assert_called_once_with(
            ["wsl", "bash", "-c", "source ~/.custom-venv/bin/activate && cd /mnt/c/myrepo && mutmut run"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60.0,
            check=False,
        )

    # 2. TimeoutExpired
    with patch("deployproof.wsl.get_wsl_path", return_value="/mnt/c/myrepo"), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="wsl", timeout=30.0)):
        res_timeout = run_wsl_mutmut(repo, [f1], timeout=30.0)
        assert res_timeout["success"] is False
        assert "timed out after 30.0s" in res_timeout["error"]

    # 3. Generic Exception
    with patch("deployproof.wsl.get_wsl_path", return_value="/mnt/c/myrepo"), \
         patch("subprocess.run", side_effect=RuntimeError("Subprocess broken")):
        res_err = run_wsl_mutmut(repo, [f1])
        assert res_err["success"] is False
        assert "WSL mutmut execution error: Subprocess broken" in res_err["error"]


def test_cli_wsl_fallback_execution(capsys, tmp_path, monkeypatch):
    """Verify CLI --wsl flag degrades gracefully to Tier 1 when venv is unconfigured."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
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

