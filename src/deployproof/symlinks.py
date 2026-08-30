"""Symlink and sandbox-escape scanner for DeployProof (CWE-61 + CWE-451)."""

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class SymlinkFinding:
    """Represents a detected symlink and its sandbox-escape analysis."""
    symlink_path: Path
    link_target_raw: str
    resolved_target: Path
    is_escape: bool
    description: str
    target_exists: bool = False


@dataclass
class SymlinkScanResult:
    """Aggregated symlink and sandbox-escape results across session files."""
    files_scanned: int
    symlinks_found: int
    escape_findings: List[SymlinkFinding] = field(default_factory=list)
    safe_symlinks: List[SymlinkFinding] = field(default_factory=list)
    duration_seconds: float = 0.0


def get_git_symlink_paths(repo_root: Path) -> Set[Path]:
    """Retrieve all files tracked with git symlink mode 120000."""
    symlinks: Set[Path] = set()
    try:
        res = subprocess.run(
            ["git", "ls-files", "-s"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if line.startswith("120000"):
                    parts = line.split(maxsplit=3)
                    if len(parts) >= 4:
                        rel_path = parts[3]
                        symlinks.add((repo_root / rel_path).resolve())
        else:
            logger.debug("git ls-files -s returned non-zero exit code %s for %s", res.returncode, repo_root)
    except (subprocess.SubprocessError, OSError) as e:
        logger.debug("Failed to query git symlinks for %s: %s", repo_root, e)
        return set()
    except Exception as e:
        logger.warning("Unexpected error querying git symlinks for %s: %s", repo_root, e)
        return set()
    return symlinks


def is_symlink_path(file_path: Path, git_symlinks: Optional[Set[Path]] = None) -> Tuple[bool, str]:
    """
    Check if a path is a symbolic link via filesystem or git mode 120000.
    
    Returns (is_symlink: bool, raw_target_string: str).
    """
    # 1. Native filesystem symlink check
    if file_path.is_symlink() or os.path.islink(file_path):
        try:
            raw_target = os.readlink(file_path)
            return True, str(raw_target)
        except OSError as e:
            logger.debug("Failed to read native symlink '%s': %s", file_path, e)
            return True, ""
        except Exception as e:
            logger.warning("Unexpected error reading native symlink '%s': %s", file_path, e)
            return True, ""

    # 2. Git-tracked mode 120000 check (for Windows environments where git checkouts store pointer text)
    if git_symlinks and file_path.resolve() in git_symlinks:
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace").strip()
            # If the file is small and contains a relative or absolute path pointer
            if content and "\n" not in content and len(content) < 1024:
                return True, content
        except OSError as e:
            logger.debug("Failed to read git symlink pointer file '%s': %s", file_path, e)
            return False, ""
        except Exception as e:
            logger.warning("Unexpected error reading git symlink pointer file '%s': %s", file_path, e)
            return False, ""

    return False, ""


def inspect_symlink(
    symlink_path: Path,
    raw_target: str,
    repo_root: Path,
) -> SymlinkFinding:
    """Analyze a symlink to verify whether its resolved target escapes repo root."""
    resolved_root = repo_root.resolve()

    # Determine resolved absolute target
    if symlink_path.is_symlink() or os.path.islink(symlink_path):
        try:
            resolved_target = symlink_path.resolve()
        except Exception:
            resolved_target = (symlink_path.parent / raw_target).resolve()
    else:
        resolved_target = (symlink_path.parent / raw_target).resolve()

    # Check if target escapes repository root
    try:
        resolved_target.relative_to(resolved_root)
        is_escape = False
    except ValueError:
        is_escape = True

    target_exists = resolved_target.exists()

    if is_escape:
        desc = (
            "CRITICAL: Symlink resolves outside the repository root directory (CWE-61/CWE-451). "
            "Apparent path differs from external destination, representing a potential GhostApproval / sandbox escape."
        )
    else:
        desc = "Safe in-repo symbolic link pointing to internal repository target."

    return SymlinkFinding(
        symlink_path=symlink_path,
        link_target_raw=raw_target,
        resolved_target=resolved_target,
        is_escape=is_escape,
        description=desc,
        target_exists=target_exists,
    )


def scan_session_files_for_symlinks(
    files: List[Path],
    repo_root: Optional[Path] = None,
) -> SymlinkScanResult:
    """Scan all session files for symlinks and sandbox-escape vulnerabilities."""
    start_time = time.time()
    root = (repo_root or Path.cwd()).resolve()

    git_symlinks = get_git_symlink_paths(root)

    escapes: List[SymlinkFinding] = []
    safe_links: List[SymlinkFinding] = []

    for f in files:
        is_link, raw_target = is_symlink_path(f, git_symlinks)
        if is_link:
            finding = inspect_symlink(f, raw_target, root)
            if finding.is_escape:
                escapes.append(finding)
            else:
                safe_links.append(finding)

    return SymlinkScanResult(
        files_scanned=len(files),
        symlinks_found=len(escapes) + len(safe_links),
        escape_findings=escapes,
        safe_symlinks=safe_links,
        duration_seconds=round(time.time() - start_time, 2),
    )
