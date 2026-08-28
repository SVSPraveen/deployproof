"""Secrets and hardcoded credentials scanner for DeployProof."""

import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Pattern, Tuple

ENV_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.staging",
    ".env.development",
    ".env.secret",
    ".env.prod",
}

# Regex patterns for well-known API keys and credentials
KNOWN_PATTERNS: List[Tuple[str, Pattern[str], str]] = [
    (
        "OpenAI / Anthropic API Key",
        re.compile(r"\b(sk-[a-zA-Z0-9_-]{20,})\b"),
        "Likely hardcoded OpenAI / Anthropic API key",
    ),
    (
        "AWS Access Key ID",
        re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
        "Likely hardcoded AWS Access Key ID",
    ),
    (
        "AWS Secret Access Key",
        re.compile(r"(?i)\b(?:aws_secret_access_key|aws_secret_key)\s*[:=]\s*[\"']([A-Za-z0-9/+=]{40})[\"']"),
        "Likely hardcoded AWS Secret Access Key",
    ),
    (
        "GitHub Token",
        re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{36,255}|github_pat_[A-Za-z0-9_]{50,})\b"),
        "Likely hardcoded GitHub Personal Access Token",
    ),
    (
        "Google API Key",
        re.compile(r"\b(AIza[0-9A-Za-z-_]{35})\b"),
        "Likely hardcoded Google / AI Studio API key",
    ),
    (
        "Slack Token",
        re.compile(r"\b(xox[baprs]-[0-9a-zA-Z-]{10,48})\b"),
        "Likely hardcoded Slack OAuth / Bot token",
    ),
    (
        "Stripe Secret Key",
        re.compile(r"\b([sr]k_(?:live|test)_[0-9a-zA-Z]{24,})\b"),
        "Likely hardcoded Stripe API Key",
    ),
    (
        "HuggingFace Token",
        re.compile(r"\b(hf_[a-zA-Z0-9]{34,})\b"),
        "Likely hardcoded HuggingFace API Token",
    ),
    (
        "Private Key Header",
        re.compile(r"(-----BEGIN [A-Z ]*PRIVATE KEY-----)"),
        "Unencrypted Private Key Block",
    ),
]

GENERIC_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b([a-z0-9_]*(?:api_?key|secret|token|password|passwd|auth_?token|access_?token|private_?key|client_?secret)[a-z0-9_]*)\s*[:=]\s*[\"']([^\"'\s]{16,})[\"']"
)

PLACEHOLDER_EXACT_OR_PREFIX = {
    "your-api-key", "your_api_key", "your-api-token", "your_token",
    "placeholder", "my-secret-key", "changeme", "change_me",
    "sample_key", "dummy_token", "fake_key", "mock_key", "test_secret", "test_token",
}


@dataclass
class SecretFinding:
    """Represents a detected secret or credential finding."""
    file_path: Path
    line_number: int
    rule_name: str
    description: str
    redacted_value: str
    snippet: str
    is_env_file: bool = False


@dataclass
class SecretsScanResult:
    """Aggregated results of a secrets scan across session files."""
    files_scanned: int
    findings: List[SecretFinding] = field(default_factory=list)
    duration_seconds: float = 0.0


def calculate_shannon_entropy(text: str) -> float:
    """Calculate the Shannon entropy of a string."""
    if not text:
        return 0.0
    counts = Counter(text)
    length = len(text)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def redact_secret(raw: str) -> str:
    """
    Safely redact a secret string, displaying only the first and last 2 characters.
    
    Example: 'sk-proj-abc1234xyz' -> 'sk****************yz'
    """
    raw = raw.strip()
    if len(raw) <= 4:
        return "****"
    prefix = raw[:2]
    suffix = raw[-2:]
    return f"{prefix}****************{suffix}"


def is_placeholder(value: str) -> bool:
    """Check if a string is an obvious placeholder rather than a real credential."""
    lowered = value.lower()
    for kw in PLACEHOLDER_EXACT_OR_PREFIX:
        if kw in lowered:
            return True
    return False


def scan_file_for_secrets(file_path: Path) -> List[SecretFinding]:
    """Scan a single file for credentials, keys, or .env tracking."""
    findings: List[SecretFinding] = []

    # 1. Tracked .env file check
    file_name = file_path.name.lower()
    if file_name in ENV_FILE_NAMES or file_name.startswith(".env."):
        findings.append(
            SecretFinding(
                file_path=file_path,
                line_number=1,
                rule_name="Tracked Environment File",
                description="Environment configuration file is tracked in git. This risks leaking private environment variables.",
                redacted_value=file_path.name,
                snippet=f"Tracked file: {file_path.name}",
                is_env_file=True,
            )
        )

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return findings

    lines = content.splitlines()
    for line_idx, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            # Skip empty lines and full line comments
            continue

        # Check known regex patterns
        for rule_name, pattern, desc in KNOWN_PATTERNS:
            match = pattern.search(line)
            if match:
                matched_str = match.group(1)
                if not is_placeholder(matched_str):
                    findings.append(
                        SecretFinding(
                            file_path=file_path,
                            line_number=line_idx,
                            rule_name=rule_name,
                            description=desc,
                            redacted_value=redact_secret(matched_str),
                            snippet=stripped,
                        )
                    )

        # Check generic high-entropy secret assignments
        assignment_match = GENERIC_ASSIGNMENT_PATTERN.search(line)
        if assignment_match:
            var_name, secret_val = assignment_match.group(1), assignment_match.group(2)
            if not is_placeholder(secret_val):
                entropy = calculate_shannon_entropy(secret_val)
                # Strings with length >= 16 and entropy >= 3.8 indicate high-entropy random credentials
                if entropy >= 3.8:
                    findings.append(
                        SecretFinding(
                            file_path=file_path,
                            line_number=line_idx,
                            rule_name="High-Entropy Credential Assignment",
                            description=f"High-entropy credential assigned to '{var_name}' (entropy: {entropy:.2f})",
                            redacted_value=redact_secret(secret_val),
                            snippet=stripped,
                        )
                    )

    return findings


def scan_session_files_for_secrets(files: List[Path]) -> SecretsScanResult:
    """Scan all session files for secrets and credentials."""
    start_time = time.time()
    all_findings: List[SecretFinding] = []

    for f in files:
        if f.is_file():
            findings = scan_file_for_secrets(f)
            all_findings.extend(findings)

    return SecretsScanResult(
        files_scanned=len(files),
        findings=all_findings,
        duration_seconds=round(time.time() - start_time, 2),
    )
