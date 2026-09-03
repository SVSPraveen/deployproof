"""WSL (Windows Subsystem for Linux) bridge for DeployProof."""

import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_WSL_VENV = "~/.deployproof-wsl-venv"


def is_windows() -> bool:
    """Check if host system is Windows."""
    return platform.system() == "Windows"


def is_wsl_available() -> bool:
    """Check if WSL is installed and accessible on Windows host."""
    if not is_windows():
        return False
    try:
        res = subprocess.run(
            ["wsl", "--status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        return res.returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def get_wsl_path(path: Path) -> Optional[str]:
    """Convert a Windows Path to a WSL POSIX path."""
    if not is_windows():
        return str(path.resolve())
    posix_style = str(path.resolve()).replace("\\", "/")
    try:
        res = subprocess.run(
            ["wsl", "wslpath", "-u", posix_style],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return None


def is_wsl_venv_configured(venv_path: str = DEFAULT_WSL_VENV) -> bool:
    """Check if Linux venv with mutmut exists inside WSL."""
    if not is_windows():
        return False
    try:
        res = subprocess.run(
            ["wsl", "bash", "-c", f"test -f {venv_path}/bin/mutmut"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        return res.returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def check_wsl_readiness(venv_path: str = DEFAULT_WSL_VENV) -> Tuple[bool, str]:
    """
    Evaluate WSL readiness for mutmut execution.
    
    Returns (ready: bool, message: str).
    """
    if not is_windows():
        return False, "Host is not Windows; WSL delegation is only applicable on Windows."

    if not is_wsl_available():
        return False, (
            "[!] WSL (Windows Subsystem for Linux) not detected.\n"
            "    To run verified mutation tests locally on Windows, install WSL (wsl --install),\n"
            "    or rely on Tier 1 pre-check locally and verify in GitHub Actions CI."
        )

    if not is_wsl_venv_configured(venv_path):
        return False, (
            f"[!] WSL environment detected, but Linux Python environment ({venv_path}) with mutmut was not found.\n"
            f"    To configure WSL for verified local testing:\n"
            f"      wsl bash -c \"python3 -m venv {venv_path} && {venv_path}/bin/pip install mutmut pytest\"\n"
            "    Running Tier 1 local pre-check instead. Full verified score will run in CI on push."
        )

    return True, "WSL and mutmut environment configured."


def run_wsl_mutmut(
    repo_root: Path,
    target_files: List[Path],
    venv_path: str = DEFAULT_WSL_VENV,
    timeout: float = 120.0,
) -> Dict[str, Any]:
    """
    Execute authoritative mutmut in WSL against scoped files.
    """
    wsl_root = get_wsl_path(repo_root)
    if not wsl_root:
        return {"success": False, "error": "Failed to resolve WSL repository path."}

    # Translate target files relative to repo root
    rel_files = []
    for f in target_files:
        try:
            rel = f.relative_to(repo_root).as_posix()
            rel_files.append(rel)
        except ValueError:
            pass

    cmd_script = f"source {venv_path}/bin/activate && cd {wsl_root} && mutmut run"
    try:
        res = subprocess.run(
            ["wsl", "bash", "-c", cmd_script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return {
            "success": res.returncode == 0,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "returncode": res.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"WSL mutmut timed out after {timeout}s."}
    except Exception as e:
        return {"success": False, "error": f"WSL mutmut execution error: {e}"}
