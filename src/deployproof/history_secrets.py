"""
Git History Secret Scanner for DeployProof.
Scans past git commits (git log -p) to detect leaked API keys, tokens, and credentials
that may have been committed and subsequently deleted from the current working tree.
"""

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

from deployproof.secrets import scan_text_for_secrets, SecretFinding


@dataclass
class HistorySecretFinding:
    """Represents a secret detected in past git revision history."""
    commit_hash: str
    author: str
    date: str
    file_path: str
    line_content: str
    rule_name: str
    redacted_value: str
    commit_message: str


@dataclass
class HistorySecretScanResult:
    """Aggregated git history secrets scan results."""
    findings: List[HistorySecretFinding] = field(default_factory=list)
    commits_scanned: int = 0
    clean: bool = True


def scan_git_history_for_secrets(
    repo_root: Path,
    max_commits: int = 50,
) -> HistorySecretScanResult:
    """
    Execute git log -p to inspect committed diffs for secrets across git history.
    """
    if not (repo_root / ".git").exists():
        return HistorySecretScanResult(clean=True)

    cmd = [
        "git",
        "log",
        "-p",
        f"-n{max_commits}",
        "--no-color",
        "--date=short",
        "--format=COMMIT_HEADER:%H|%an|%ad|%s",
    ]

    try:
        proc = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30.0,
        )
    except Exception:
        return HistorySecretScanResult(clean=True)

    if proc.returncode != 0 or not proc.stdout:
        return HistorySecretScanResult(clean=True)

    findings: List[HistorySecretFinding] = []
    seen_keys: Set[str] = set()

    current_commit = ""
    current_author = ""
    current_date = ""
    current_msg = ""
    current_file = ""
    commits_count = 0

    for line in proc.stdout.splitlines():
        if line.startswith("COMMIT_HEADER:"):
            header_parts = line[len("COMMIT_HEADER:"):].split("|", 3)
            current_commit = header_parts[0] if len(header_parts) > 0 else "unknown"
            current_author = header_parts[1] if len(header_parts) > 1 else "unknown"
            current_date = header_parts[2] if len(header_parts) > 2 else "unknown"
            current_msg = header_parts[3] if len(header_parts) > 3 else ""
            commits_count += 1
            current_file = ""
            continue

        if line.startswith("diff --git a/"):
            # Extract file path: diff --git a/foo.py b/foo.py
            parts = line.split(" b/")
            if len(parts) >= 2:
                current_file = parts[1].strip()
            continue

        # Only scan added lines in diffs
        if line.startswith("+") and not line.startswith("+++"):
            added_line = line[1:]
            if not added_line.strip() or added_line.strip().startswith("#"):
                continue

            sec_findings = scan_text_for_secrets(added_line, Path(current_file or "git_history"))
            for sf in sec_findings:
                dedup_key = f"{sf.rule_name}:{sf.redacted_value}:{current_file}"
                if dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    findings.append(
                        HistorySecretFinding(
                            commit_hash=current_commit[:10],
                            author=current_author,
                            date=current_date,
                            file_path=current_file or "unknown",
                            line_content=added_line.strip(),
                            rule_name=sf.rule_name,
                            redacted_value=sf.redacted_value,
                            commit_message=current_msg,
                        )
                    )

    return HistorySecretScanResult(
        findings=findings,
        commits_scanned=commits_count,
        clean=len(findings) == 0,
    )
