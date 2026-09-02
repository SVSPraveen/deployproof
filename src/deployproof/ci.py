"""
GitHub Actions & CI/CD Integration for DeployProof.

Provides automatic GitHub Actions PR inline annotations (::error / ::warning)
and rich Markdown step summary dashboard generation ($GITHUB_STEP_SUMMARY).
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from deployproof.control_flow import ControlFlowScanSummary
from deployproof.cve import CveScanResult
from deployproof.dependencies import DependencyScanSummary
from deployproof.history_secrets import HistorySecretScanResult
from deployproof.mocks import MockScanSummary
from deployproof.mutator import MutationResult
from deployproof.sast import SastScanResult
from deployproof.secrets import SecretsScanResult
from deployproof.symlinks import SymlinkScanResult
from deployproof.synthesizer import synthesize_tests_for_surviving_mutants


def is_github_actions() -> bool:
    """Return True if running in a GitHub Actions runner."""
    return os.environ.get("GITHUB_ACTIONS") == "true" or bool(os.environ.get("GITHUB_STEP_SUMMARY"))


def _escape_github_property(val: str) -> str:
    """Escape special characters for GitHub Actions workflow command properties."""
    return str(val).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A").replace(":", "%3A").replace(",", "%2C")


def _escape_github_data(val: str) -> str:
    """Escape special characters for GitHub Actions workflow command message data."""
    return str(val).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def format_github_annotations(
    result: MutationResult,
    target_files: List[Path],
    secrets_result: Optional[SecretsScanResult] = None,
    symlink_result: Optional[SymlinkScanResult] = None,
    dependency_result: Optional[DependencyScanSummary] = None,
    mock_result: Optional[MockScanSummary] = None,
    control_flow_result: Optional[ControlFlowScanSummary] = None,
    sast_result: Optional[SastScanResult] = None,
    history_secrets_result: Optional[HistorySecretScanResult] = None,
    cve_result: Optional[CveScanResult] = None,
    repo_root: Optional[Path] = None,
) -> List[str]:
    """
    Generate GitHub Actions workflow annotation commands (::error / ::warning).
    """
    root = (repo_root or Path.cwd()).resolve()
    commands: List[str] = []

    # 1. Collection errors
    if result.collection_error:
        msg = _escape_github_data(f"Test collection failure: {result.collection_error}")
        commands.append(f"::error title=DeployProof%20Test%20Collection%20Error::{msg}")

    # 2. Symlink Sandbox Escapes (Critical Error)
    if symlink_result and symlink_result.escape_findings:
        for f in symlink_result.escape_findings:
            try:
                rel = f.symlink_path.relative_to(root).as_posix()
            except ValueError:
                rel = f.symlink_path.as_posix()
            msg = _escape_github_data(f"Symlink escapes repo sandbox: points to {f.resolved_target}")
            commands.append(f"::error file={rel},title=Symlink%20Sandbox%20Escape::{msg}")

    # 3. Secrets / Credential Findings (Critical Error)
    if secrets_result and secrets_result.findings:
        for f in secrets_result.findings:
            try:
                rel = f.file_path.relative_to(root).as_posix()
            except ValueError:
                rel = f.file_path.as_posix()
            msg = _escape_github_data(f"[{f.rule_name}] {f.description} (Value: {f.redacted_value})")
            commands.append(f"::error file={rel},line={f.line_number},title=Leaked%20Secret%20Detected::{msg}")

    # 4. SAST Vulnerabilities (High / Critical)
    if sast_result and sast_result.findings:
        for f in sast_result.findings:
            try:
                rel = f.file_path.relative_to(root).as_posix()
            except ValueError:
                rel = f.file_path.as_posix()
            level = "error" if f.severity in ("CRITICAL", "HIGH") else "warning"
            msg = _escape_github_data(f"[{f.cwe}] {f.rule_name}: {f.description}")
            commands.append(f"::{level} file={rel},line={f.line_number},title=SAST%20Security%20Vulnerability::{msg}")

    # 5. CVE Vulnerabilities
    if cve_result and cve_result.advisories:
        for a in cve_result.advisories:
            level = "error" if a.severity in ("CRITICAL", "HIGH") else "warning"
            msg = _escape_github_data(f"Vulnerable package '{a.package_name}=={a.installed_version}': {a.summary} (Fixed in: {a.fixed_version})")
            commands.append(f"::{level} title=Dependency%20CVE%20Advisory::{msg}")

    # 6. Control Flow / Swallowed Exceptions
    if control_flow_result and control_flow_result.findings:
        for f in control_flow_result.findings:
            try:
                rel = f.file_path.relative_to(root).as_posix()
            except ValueError:
                rel = f.file_path.as_posix()
            msg = _escape_github_data(f"[{f.pattern_name}] {f.description}")
            commands.append(f"::warning file={rel},line={f.line_number},title=Control%20Flow%20Issue::{msg}")

    # 7. Surviving Mutants (Warning)
    if result.survived_mutants:
        for m in result.survived_mutants:
            try:
                rel = m.file_path.relative_to(root).as_posix()
            except ValueError:
                rel = m.file_path.as_posix()
            msg = _escape_github_data(f"Mutant survived: {m.description}. Original: '{m.original_line}' -> Mutated: '{m.mutated_line}'")
            commands.append(f"::warning file={rel},line={m.line_number},title=Surviving%20Mutation%20Test%20Gap::{msg}")

    return commands


def format_github_step_summary(
    result: MutationResult,
    target_files: List[Path],
    secrets_result: Optional[SecretsScanResult] = None,
    symlink_result: Optional[SymlinkScanResult] = None,
    dependency_result: Optional[DependencyScanSummary] = None,
    mock_result: Optional[MockScanSummary] = None,
    control_flow_result: Optional[ControlFlowScanSummary] = None,
    sast_result: Optional[SastScanResult] = None,
    history_secrets_result: Optional[HistorySecretScanResult] = None,
    cve_result: Optional[CveScanResult] = None,
    strict_mocks: bool = False,
    strict_error_handling: bool = False,
    repo_root: Optional[Path] = None,
    threshold: float = 80.0,
) -> str:
    """
    Generate a rich GitHub Flavored Markdown summary dashboard for $GITHUB_STEP_SUMMARY.
    """
    root = (repo_root or Path.cwd()).resolve()

    # Determine overall status
    is_passed = (
        (result.mutation_score is not None and result.mutation_score >= threshold)
        and not result.untested_files
        and not result.collection_error
        and (not secrets_result or not secrets_result.findings)
        and (not symlink_result or not symlink_result.escape_findings)
        and (not dependency_result or dependency_result.high_risk_count == 0)
        and (not strict_mocks or not mock_result or mock_result.total_findings == 0)
        and (not strict_error_handling or not control_flow_result or control_flow_result.total_findings == 0)
        and (not sast_result or (sast_result.critical_count == 0 and sast_result.high_count == 0))
        and (not history_secrets_result or history_secrets_result.clean)
        and (not cve_result or (cve_result.critical_count == 0 and cve_result.high_count == 0))
    )

    badge = "## 🛡️ DeployProof Verification: " + ("✅ PASSED" if is_passed else "❌ FAILED")
    
    score_display = f"{result.mutation_score:.1f}%" if result.mutation_score is not None else "N/A"
    mut_status = "✅ PASSED" if (result.mutation_score is not None and result.mutation_score >= threshold) else "❌ FAILED"
    if result.collection_error:
        mut_status = "❌ ERROR"

    sast_count = len(sast_result.findings) if sast_result else 0
    sast_status = "✅ CLEAN" if sast_count == 0 else "❌ FAILED"

    secrets_count = len(secrets_result.findings) if secrets_result else 0
    secrets_status = "✅ CLEAN" if secrets_count == 0 else "❌ FAILED"

    history_count = len(history_secrets_result.findings) if history_secrets_result else 0
    history_status = "✅ CLEAN" if history_count == 0 else "❌ FAILED"

    cve_count = len(cve_result.advisories) if cve_result else 0
    cve_status = "✅ CLEAN" if cve_count == 0 else "❌ FAILED"

    symlink_count = len(symlink_result.escape_findings) if symlink_result else 0
    symlink_status = "✅ CLEAN" if symlink_count == 0 else "❌ FAILED"

    flow_count = control_flow_result.total_findings if control_flow_result else 0
    flow_status = "✅ CLEAN" if (not strict_error_handling or flow_count == 0) else "❌ FAILED"

    lines: List[str] = [
        badge,
        "",
        f"> **Deterministic Pre-Deployment Verification Gate** &bull; Scope: `{len(target_files)}` files evaluated &bull; Time: `{result.duration_seconds:.2f}s`",
        "",
        "### 📊 Gate Verification Summary",
        "",
        "| Verification Gate | Status | Findings / Metrics |",
        "| :--- | :--- | :--- |",
        f"| 🧬 **Mutation Testing** | {mut_status} ({score_display}) | `{result.killed_mutants}/{result.total_mutants}` killed (Threshold: `{threshold}%`) |",
        f"| 🔒 **OWASP Top 10 SAST** | {sast_status} | `{sast_count}` security vulnerabilities detected |",
        f"| 🔑 **Secrets & Credentials** | {secrets_status} | `{secrets_count}` hardcoded secrets in working tree |",
        f"| 📜 **Git History Secrets** | {history_status} | `{history_count}` leaked credentials in commit log |",
        f"| 📦 **Dependencies & CVEs** | {cve_status} | `{cve_count}` known CVE advisories flagged |",
        f"| 🔗 **Symlink Sandbox Escape** | {symlink_status} | `{symlink_count}` path traversal escape symlinks |",
        f"| ⚙️ **Control Flow & Mocks** | {flow_status} | `{flow_count}` bare excepts / swallowed exceptions |",
        "",
    ]

    # Surviving Mutants & Synthesized Tests Section
    if result.survived_mutants:
        lines.append(f"### 🧬 Surviving Mutants & Self-Healing Tests ({len(result.survived_mutants)})")
        lines.append("")
        synth_tests = synthesize_tests_for_surviving_mutants(result.survived_mutants, repo_root=root)
        synth_map = {st.mutant_id: st for st in synth_tests}

        for idx, m in enumerate(result.survived_mutants, 1):
            try:
                rel_f = m.file_path.relative_to(root).as_posix()
            except ValueError:
                rel_f = m.file_path.as_posix()
            lines.append(f"<details><summary><b>[{idx}] {rel_f}:{m.line_number}</b> — <code>{m.description}</code></summary>")
            lines.append("")
            lines.append(f"* **Original Code**: `{m.original_line.strip()}`")
            lines.append(f"* **Mutated Code**: `{m.mutated_line.strip()}`")
            if m.mutant_id in synth_map:
                st = synth_map[m.mutant_id]
                lines.append(f"* **Strategy**: `{st.strategy}`")
                lines.append("```python")
                lines.append(st.test_code.strip())
                lines.append("```")
            lines.append("</details>")
            lines.append("")

    # Security Details Section (if any vulnerabilities)
    if (secrets_result and secrets_result.findings) or (sast_result and sast_result.findings) or (cve_result and cve_result.advisories):
        lines.append("### 🚨 Security Audit Findings")
        lines.append("")
        if secrets_result and secrets_result.findings:
            for s in secrets_result.findings:
                lines.append(f"- 🔑 **Secret**: `{s.file_path}:{s.line_number}` [{s.rule_name}] `{s.redacted_value}`")
        if sast_result and sast_result.findings:
            for sf in sast_result.findings:
                lines.append(f"- 🔒 **SAST**: `{sf.file_path}:{sf.line_number}` [{sf.severity}] {sf.rule_name} ({sf.cwe})")
        if cve_result and cve_result.advisories:
            for c in cve_result.advisories:
                lines.append(f"- 📦 **CVE**: `{c.package_name}=={c.installed_version}` [{c.severity}] {c.cve_id}: {c.summary}")
        lines.append("")

    lines.append("---")
    lines.append("*Generated automatically by [DeployProof](https://github.com/SVSPraveen/DeployProof)*")
    return "\n".join(lines) + "\n"


def write_github_step_summary_if_enabled(
    summary_markdown: str,
    override_path: Optional[Path] = None,
) -> bool:
    """
    Append summary markdown to $GITHUB_STEP_SUMMARY if active in environment.
    """
    summary_file = override_path
    if not summary_file:
        env_val = os.environ.get("GITHUB_STEP_SUMMARY")
        if env_val:
            summary_file = Path(env_val)

    if summary_file:
        try:
            summary_file.parent.mkdir(parents=True, exist_ok=True)
            with open(summary_file, "a", encoding="utf-8") as f:
                f.write(summary_markdown)
            return True
        except Exception:
            return False
    return False
