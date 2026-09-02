"""Terminal output reporter for DeployProof."""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from deployproof import __version__
from deployproof.control_flow import ControlFlowScanSummary
from deployproof.cve import CveScanResult
from deployproof.dependencies import DependencyScanSummary
from deployproof.history_secrets import HistorySecretScanResult
from deployproof.mocks import MockScanSummary
from deployproof.mutator import MutationResult
from deployproof.sast import SastScanResult
from deployproof.secrets import SecretsScanResult
from deployproof.symlinks import SymlinkScanResult

LARGE_FILE_LOC_THRESHOLD = 300


def format_json_report(
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
    version: Optional[str] = None,
) -> str:
    """Format all scan findings and mutation results as a structured JSON string."""
    effective_version = version or __version__
    root = (repo_root or Path.cwd()).resolve()
    strict_mocks_triggered = bool(strict_mocks and mock_result and (mock_result.total_findings > 0))
    strict_error_triggered = bool(strict_error_handling and control_flow_result and (control_flow_result.total_findings > 0))
    sast_critical = bool(sast_result and (sast_result.critical_count > 0 or sast_result.high_count > 0))
    history_secret_found = bool(history_secrets_result and not history_secrets_result.clean)
    cve_critical = bool(cve_result and (cve_result.critical_count > 0 or cve_result.high_count > 0))

    has_security_failure = bool(
        (secrets_result and secrets_result.findings)
        or (symlink_result and symlink_result.escape_findings)
        or (dependency_result and dependency_result.high_risk_count > 0)
        or strict_mocks_triggered
        or strict_error_triggered
        or sast_critical
        or history_secret_found
        or cve_critical
    )
    is_passed = (
        not result.collection_error
        and not has_security_failure
        and not result.untested_files
        and (result.mutation_score is not None and result.mutation_score >= threshold)
    )
    status_str = "error" if result.collection_error else ("passed" if is_passed else "failed")

    scope_files = []
    for f in target_files:
        try:
            rel = f.relative_to(root).as_posix()
        except ValueError:
            rel = f.as_posix()
        try:
            loc = len(f.read_text(encoding="utf-8", errors="replace").splitlines())
        except Exception:
            loc = 0
        scope_files.append({"file": rel, "loc": loc, "is_large": loc >= LARGE_FILE_LOC_THRESHOLD})

    surviving_mutants_data = []
    for m in result.survived_mutants:
        try:
            rel_f = m.file_path.relative_to(root).as_posix()
        except ValueError:
            rel_f = m.file_path.as_posix()
        surviving_mutants_data.append(
            {
                "file": rel_f,
                "line": m.line_number,
                "description": m.description,
                "original_code": m.original_line,
                "mutated_code": m.mutated_line,
            }
        )

    skipped_constructs_data = []
    for s in result.skipped_constructs:
        try:
            rel_f = s.file_path.relative_to(root).as_posix()
        except ValueError:
            rel_f = s.file_path.as_posix()
        skipped_constructs_data.append(
            {
                "file": rel_f,
                "line": s.line_number,
                "construct": s.construct_name,
                "reason": getattr(s, "description", getattr(s, "reason", "")),
            }
        )

    pruned_equivalent_data = []
    for pe in getattr(result, "pruned_equivalent_mutants", []):
        try:
            rel_f = pe.file_path.relative_to(root).as_posix()
        except ValueError:
            rel_f = pe.file_path.as_posix()
        pruned_equivalent_data.append(
            {
                "file": rel_f,
                "line": pe.line_number,
                "category": pe.category,
                "description": pe.description,
                "original_code": pe.original_line,
            }
        )

    synthesized_tests_data = []
    if result.survived_mutants:
        from deployproof.synthesizer import synthesize_tests_for_surviving_mutants
        synth_tests = synthesize_tests_for_surviving_mutants(result.survived_mutants, repo_root=root)
        for st in synth_tests:
            try:
                rel_f = st.file_path.relative_to(root).as_posix()
            except ValueError:
                rel_f = st.file_path.as_posix()
            synthesized_tests_data.append(
                {
                    "test_name": st.test_name,
                    "target_file": rel_f,
                    "target_line": st.line_number,
                    "function_name": st.function_name,
                    "strategy": st.strategy,
                    "test_code": st.test_code,
                }
            )

    untested_files_data = []
    for u in result.untested_files:
        try:
            rel_f = u.relative_to(root).as_posix()
        except ValueError:
            rel_f = u.as_posix()
        untested_files_data.append(rel_f)

    secrets_findings_data = []
    if secrets_result and secrets_result.findings:
        for f in secrets_result.findings:
            try:
                rel_f = f.file_path.relative_to(root).as_posix()
            except ValueError:
                rel_f = f.file_path.as_posix()
            secrets_findings_data.append(
                {
                    "file": rel_f,
                    "line": f.line_number,
                    "rule": f.rule_name,
                    "severity": "HIGH",
                    "redacted_value": f.redacted_value,
                    "snippet": f.snippet,
                    "message": f.description,
                }
            )

    symlink_escapes_data = []
    if symlink_result and symlink_result.escape_findings:
        for f in symlink_result.escape_findings:
            try:
                rel_f = f.symlink_path.relative_to(root).as_posix()
            except ValueError:
                rel_f = f.symlink_path.as_posix()
            symlink_escapes_data.append(
                {
                    "file": rel_f,
                    "target_raw": f.link_target_raw,
                    "resolved_target": str(f.resolved_target),
                    "target_exists": f.target_exists,
                    "severity": "CRITICAL",
                    "message": f.description,
                }
            )

    dep_findings_data = []
    unscanned_sources_data = []
    if dependency_result and dependency_result.findings:
        for f in dependency_result.findings:
            try:
                rel_f = f.source_file.relative_to(root).as_posix()
            except ValueError:
                rel_f = f.source_file.as_posix()
            if f.status in ("HIGH_RISK", "MEDIUM_RISK", "UNKNOWN"):
                dep_findings_data.append(
                    {
                        "package": f.package_name,
                        "import_name": f.import_name,
                        "file": rel_f,
                        "line": f.lineno,
                        "source_type": f.source_type,
                        "status": f.status,
                        "severity": "HIGH" if f.status == "HIGH_RISK" else "MEDIUM" if f.status == "MEDIUM_RISK" else "UNKNOWN",
                        "age_days": f.age_days,
                        "first_release_date": f.first_release_date,
                        "message": f.details,
                    }
                )
            elif f.status == "UNSCANNED":
                unscanned_sources_data.append(
                    {"source": f.import_name, "file": rel_src, "line": f.lineno, "source_type": f.source_type, "reason": f.details}
                )

    mock_findings_data = []
    if mock_result and mock_result.findings:
        for f in mock_result.findings:
            try:
                rel_f = f.file_path.relative_to(root).as_posix()
            except ValueError:
                rel_f = f.file_path.as_posix()
            mock_findings_data.append(
                {
                    "file": rel_f,
                    "line": f.line_number,
                    "mock_type": f.mock_type,
                    "what": f.description,
                    "code": f.snippet,
                    "message": f"Newly added mock usage detected in diff: {f.description}",
                }
            )

    control_flow_findings_data = []
    if control_flow_result and control_flow_result.findings:
        for f in control_flow_result.findings:
            try:
                rel_f = f.file_path.relative_to(root).as_posix()
            except ValueError:
                rel_f = f.file_path.as_posix()
            control_flow_findings_data.append(
                {"file": rel_f, "line": f.line_number, "rule": f.rule_id, "severity": f.severity, "snippet": f.snippet, "message": f.message}
            )

    sast_findings_data = []
    if sast_result and sast_result.findings:
        for f in sast_result.findings:
            try:
                rel_f = f.file_path.relative_to(root).as_posix()
            except ValueError:
                rel_f = f.file_path.as_posix()
            sast_findings_data.append(
                {
                    "file": rel_f,
                    "line": f.line_number,
                    "rule_id": f.rule_id,
                    "rule_name": f.rule_name,
                    "severity": f.severity,
                    "snippet": f.snippet,
                    "description": f.description,
                    "cwe": f.cwe,
                    "owasp": f.owasp_category,
                }
            )

    history_secrets_data = []
    if history_secrets_result and history_secrets_result.findings:
        for f in history_secrets_result.findings:
            history_secrets_data.append(
                {
                    "commit": f.commit_hash,
                    "author": f.author,
                    "date": f.date,
                    "file": f.file_path,
                    "rule": f.rule_name,
                    "redacted_value": f.redacted_value,
                    "snippet": f.line_content,
                    "commit_message": f.commit_message,
                }
            )

    cve_advisories_data = []
    if cve_result and cve_result.advisories:
        for a in cve_result.advisories:
            cve_advisories_data.append(
                {
                    "package": a.package_name,
                    "version": a.installed_version,
                    "cve_id": a.cve_id,
                    "summary": a.summary,
                    "severity": a.severity,
                    "fixed_version": a.fixed_version,
                    "url": a.advisory_url,
                }
            )

    data: Dict[str, Any] = {
        "version": effective_version,
        "status": status_str,
        "summary": {
            "target_files_count": len(target_files),
            "mutation_score": result.mutation_score,
            "collection_error": result.collection_error,
            "threshold": threshold,
            "secrets_found": len(secrets_findings_data),
            "symlink_escapes_found": len(symlink_escapes_data),
            "dependency_findings": {
                "high_risk": dependency_result.high_risk_count if dependency_result else 0,
                "medium_risk": dependency_result.medium_risk_count if dependency_result else 0,
                "ok": dependency_result.ok_count if dependency_result else 0,
                "unknown": dependency_result.unknown_count if dependency_result else 0,
                "unscanned": len(unscanned_sources_data),
            },
            "mock_usages_found": len(mock_findings_data),
            "control_flow_findings": len(control_flow_findings_data),
            "sast_findings": len(sast_findings_data),
            "history_secrets_found": len(history_secrets_data),
            "cve_advisories_found": len(cve_advisories_data),
            "strict_mocks_active": strict_mocks,
            "strict_mocks_triggered": strict_mocks_triggered,
            "strict_error_handling_active": strict_error_handling,
            "strict_error_handling_triggered": strict_error_triggered,
        },
        "scope": {"target_files": scope_files},
        "mutation_testing": {
            "score": result.mutation_score,
            "collection_error": result.collection_error,
            "threshold": threshold,
            "total_mutants": result.total_mutants,
            "killed_mutants": result.killed_mutants,
            "survived_mutants_count": len(surviving_mutants_data),
            "runner_errors_count": len(result.runner_errors),
            "valid_mutants_count": result.killed_mutants + len(surviving_mutants_data),
            "duration_seconds": result.duration_seconds,
            "surviving_mutants": surviving_mutants_data,
            "skipped_constructs": skipped_constructs_data,
            "pruned_equivalent_count": len(pruned_equivalent_data),
            "pruned_equivalent_mutants": pruned_equivalent_data,
            "synthesized_tests_count": len(synthesized_tests_data),
            "synthesized_tests": synthesized_tests_data,
            "untested_files": untested_files_data,
        },
        "secrets": {
            "clean": len(secrets_findings_data) == 0,
            "files_scanned": secrets_result.files_scanned if secrets_result else len(target_files),
            "findings": secrets_findings_data,
        },
        "git_history_secrets": {
            "clean": len(history_secrets_data) == 0,
            "commits_scanned": history_secrets_result.commits_scanned if history_secrets_result else 0,
            "findings": history_secrets_data,
        },
        "sast": {
            "clean": len(sast_findings_data) == 0,
            "files_scanned": sast_result.files_scanned if sast_result else len(target_files),
            "findings": sast_findings_data,
        },
        "symlinks": {
            "clean": len(symlink_escapes_data) == 0,
            "files_scanned": symlink_result.files_scanned if symlink_result else len(target_files),
            "findings": symlink_escapes_data,
        },
        "dependencies": {
            "clean": bool(not dep_findings_data),
            "total_scanned": dependency_result.total_scanned if dependency_result else 0,
            "findings": dep_findings_data,
            "unscanned_sources": unscanned_sources_data,
        },
        "cve_vulnerabilities": {
            "clean": len(cve_advisories_data) == 0,
            "packages_checked": cve_result.packages_checked if cve_result else 0,
            "advisories": cve_advisories_data,
        },
        "mocks": {
            "clean": len(mock_findings_data) == 0,
            "strict_gate_triggered": strict_mocks_triggered,
            "findings": mock_findings_data,
        },
        "control_flow": {
            "clean": len(control_flow_findings_data) == 0,
            "strict_gate_triggered": strict_error_triggered,
            "findings": control_flow_findings_data,
        },
    }
    return json.dumps(data, indent=2)


def format_report(
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
    """Format mutation testing results, security scans, SAST, CVEs, and dependency checks as terminal output."""
    lines: List[str] = []
    lines.append("DeployProof - LOCAL PRE-CHECK (approximate) - not the verified score")
    lines.append("=" * 68)
    root = (repo_root or Path.cwd()).resolve()
    file_count = len(target_files)
    lines.append(f"\nTarget Scope ({file_count} file{('s' if file_count != 1 else '')} evaluated):")
    if target_files:
        for f in target_files:
            try:
                rel = f.relative_to(root)
            except ValueError:
                rel = f
            try:
                loc = len(f.read_text(encoding="utf-8", errors="replace").splitlines())
            except Exception:
                loc = 0
            if loc >= LARGE_FILE_LOC_THRESHOLD:
                lines.append(f"  * {rel} ({loc} LOC) - [!] Large file: pre-check may take several minutes.")
            else:
                lines.append(f"  * {rel}")
    else:
        lines.append("  (No modified Python files in scope)")

    # 1. Symlinks
    lines.append("\nSymlink & Sandbox Escape Scan (CWE-61/CWE-451):")
    if symlink_result and symlink_result.escape_findings:
        escape_count = len(symlink_result.escape_findings)
        lines.append(f"  [!] {escape_count} sandbox-escape symlink{('s' if escape_count != 1 else '')} detected:")
        for idx, finding in enumerate(symlink_result.escape_findings, 1):
            try:
                rel_sym = finding.symlink_path.relative_to(root)
            except ValueError:
                rel_sym = finding.symlink_path
            lines.append(f"\n    [{idx}] {rel_sym} -> {finding.link_target_raw}")
            lines.append(f"        Apparent Path:   {rel_sym}")
            lines.append(f"        Resolved Target: {finding.resolved_target} (Exists on disk: {finding.target_exists})")
            lines.append("        Severity:        CRITICAL (Escapes repository sandbox)")
            lines.append(f"        Note:            {finding.description}")
    elif symlink_result and symlink_result.safe_symlinks:
        safe_count = len(symlink_result.safe_symlinks)
        lines.append(
            f"  Clean: No sandbox-escape symlinks detected across {symlink_result.files_scanned} session files ({safe_count} safe in-repo symlink{('s' if safe_count != 1 else '')} verified)."
        )
    else:
        scanned_count = symlink_result.files_scanned if symlink_result else file_count
        lines.append(f"  Clean: No symlinks or sandbox-escape traversal links detected across {scanned_count} session file{('s' if scanned_count != 1 else '')}.")

    # 2. Secrets Scan
    lines.append("\nSecrets & Credentials Pre-Push Scan:")
    if secrets_result and secrets_result.findings:
        findings_count = len(secrets_result.findings)
        lines.append(f"  [!] {findings_count} potential secret/credential finding{('s' if findings_count != 1 else '')} detected:")
        for idx, finding in enumerate(secrets_result.findings, 1):
            try:
                rel_path = finding.file_path.relative_to(root)
            except ValueError:
                rel_path = finding.file_path
            lines.append(f"\n    [{idx}] {rel_path}:{finding.line_number} [{finding.rule_name}]")
            lines.append(f"        Redacted: {finding.redacted_value}")
            if finding.snippet:
                lines.append(f"        Snippet:  {finding.snippet}")
            lines.append(f"        Note:     {finding.description}")
    else:
        scanned_count = secrets_result.files_scanned if secrets_result else file_count
        lines.append(f"  Clean: No hardcoded secrets or tracked .env files detected across {scanned_count} session file{('s' if scanned_count != 1 else '')}.")

    # 3. Git History Secrets Scan
    if history_secrets_result and history_secrets_result.findings:
        lines.append("\nGit History Secrets & Credential Leaks (git log -p):")
        lines.append(f"  [!] {len(history_secrets_result.findings)} leaked credentials detected in commit history:")
        for idx, finding in enumerate(history_secrets_result.findings, 1):
            lines.append(f"\n    [{idx}] Commit {finding.commit_hash} ({finding.date}) by {finding.author}")
            lines.append(f"        File:     {finding.file_path}")
            lines.append(f"        Rule:     {finding.rule_name}")
            lines.append(f"        Redacted: {finding.redacted_value}")
            lines.append(f"        Snippet:  {finding.line_content}")
            lines.append(f"        Message:  {finding.commit_message}")

    # 4. SAST Vulnerability Scan (OWASP Top 10)
    lines.append("\nStatic Application Security Testing (SAST / OWASP Top 10):")
    if sast_result and sast_result.findings:
        lines.append(f"  [!] {len(sast_result.findings)} security vulnerability finding(s) detected:")
        for idx, finding in enumerate(sast_result.findings, 1):
            try:
                rel_path = finding.file_path.relative_to(root)
            except ValueError:
                rel_path = finding.file_path
            lines.append(f"\n    [{idx}] {rel_path}:{finding.line_number} [{finding.rule_name}]")
            lines.append(f"        Severity: {finding.severity} ({finding.cwe} | {finding.owasp_category})")
            lines.append(f"        Note:     {finding.description}")
            if finding.snippet:
                lines.append(f"        Snippet:  {finding.snippet}")
    else:
        sast_scanned = sast_result.files_scanned if sast_result else file_count
        lines.append(f"  Clean: 0 OWASP Top 10 security injection or deserialization vulnerabilities detected across {sast_scanned} files.")

    # 5. Dependency & Slopsquatting Scan
    lines.append("\nDependency & Slopsquatting Scan (PyPI Registry & Age Analysis):")
    if dependency_result and (dependency_result.high_risk_count > 0 or dependency_result.medium_risk_count > 0):
        flagged_count = dependency_result.high_risk_count + dependency_result.medium_risk_count
        lines.append(f"  [!] {flagged_count} suspicious dependency finding{('s' if flagged_count != 1 else '')} detected:")
        idx = 1
        for finding in dependency_result.findings:
            if finding.status in ("HIGH_RISK", "MEDIUM_RISK"):
                try:
                    rel_src = finding.source_file.relative_to(root)
                except ValueError:
                    rel_src = finding.source_file
                src_str = f"{rel_src}:{finding.lineno}" if finding.lineno else str(rel_src)
                lines.append(f"\n    [{idx}] {finding.package_name} [{finding.status}]")
                lines.append(f"        Source:         {src_str} ({finding.source_type})")
                if finding.status == "HIGH_RISK":
                    lines.append("        Classification: HIGH RISK (Package does NOT exist on PyPI)")
                elif finding.status == "MEDIUM_RISK":
                    lines.append(
                        f"        Classification: MEDIUM RISK (Registered {finding.age_days} day{('s' if finding.age_days != 1 else '')} ago, first published {finding.first_release_date})"
                    )
                lines.append(f"        Note:           {finding.details}")
                idx += 1
    elif dependency_result and dependency_result.total_scanned > 0:
        lines.append(f"  Clean: {dependency_result.ok_count} external package{('s' if dependency_result.ok_count != 1 else '')} verified on PyPI (0 hallucinated, 0 recently registered).")
    else:
        scanned_count = secrets_result.files_scanned if secrets_result else file_count
        lines.append(f"  Clean: No new external packages introduced across {scanned_count} session file{('s' if scanned_count != 1 else '')}.")

    if dependency_result and dependency_result.unknown_count > 0:
        lines.append(f"\n  [?] {dependency_result.unknown_count} unverified dependency check{('s' if dependency_result.unknown_count != 1 else '')} (Network / registry query error):")
        for finding in dependency_result.findings:
            if finding.status == "UNKNOWN":
                try:
                    rel_src = finding.source_file.relative_to(root)
                except ValueError:
                    rel_src = finding.source_file
                src_str = f"{rel_src}:{finding.lineno}" if finding.lineno else str(rel_src)
                lines.append(f"    * {finding.package_name} (Source: {src_str}) - {finding.details}")

    if dependency_result and dependency_result.unscanned_count > 0:
        lines.append(f"\n  [!] {dependency_result.unscanned_count} unscanned dependency source{('s' if dependency_result.unscanned_count != 1 else '')} (seen, not checked):")
        for finding in dependency_result.findings:
            if finding.status == "UNSCANNED":
                try:
                    rel_src = finding.source_file.relative_to(root)
                except ValueError:
                    rel_src = finding.source_file
                src_str = f"{rel_src}:{finding.lineno}" if finding.lineno else str(rel_src)
                lines.append(f"    * {finding.import_name} (Source: {src_str}) - {finding.details}")

    # 6. Dependency CVE Vulnerabilities (OSV Database)
    if cve_result and cve_result.advisories:
        lines.append(f"\nDependency CVE Vulnerabilities (OSV Database):")
        lines.append(f"  [!] {len(cve_result.advisories)} known CVE advisory/advisories impacting project dependencies:")
        for idx, adv in enumerate(cve_result.advisories, 1):
            lines.append(f"\n    [{idx}] {adv.package_name} ({adv.installed_version}) [{adv.cve_id}]")
            lines.append(f"        Severity: {adv.severity}")
            lines.append(f"        Summary:  {adv.summary}")
            if adv.fixed_version:
                lines.append(f"        Fix:      Upgrade to version >= {adv.fixed_version}")
            if adv.advisory_url:
                lines.append(f"        URL:      {adv.advisory_url}")

    # 7. Mock Usages
    lines.append("\nMock Usage Introduced (flagged for review):")
    if mock_result and mock_result.total_findings > 0:
        warning_label = "[!] STRICT GATE TRIGGERED:" if strict_mocks else "[*] Notice:"
        lines.append(f"  {warning_label} {mock_result.total_findings} newly added mock/stub usage{('s' if mock_result.total_findings != 1 else '')} detected:")
        for idx, finding in enumerate(mock_result.findings, 1):
            try:
                rel_path = finding.file_path.relative_to(root)
            except ValueError:
                rel_path = finding.file_path
            lines.append(f"\n    [{idx}] {rel_path}:{finding.line_number} [{finding.mock_type}]")
            lines.append(f"        What: {finding.description}")
            if finding.snippet:
                lines.append(f"        Code: {finding.snippet}")
    else:
        test_scanned = len(mock_result.files_scanned) if mock_result else 0
        if test_scanned > 0:
            lines.append(f"  Clean: No new mocks, monkeypatches, or stub fixtures introduced across {test_scanned} session test file{('s' if test_scanned != 1 else '')}.")
        else:
            lines.append("  Clean: No modified test files in scope.")

    # 8. Control Flow
    lines.append("\nControl Flow & Error Handling (flagged for review):")
    if control_flow_result and control_flow_result.total_findings > 0:
        warning_label = "[!] STRICT GATE TRIGGERED:" if strict_error_handling else "[*] Notice:"
        lines.append(f"  {warning_label} {control_flow_result.total_findings} control flow / error handling issue{('s' if control_flow_result.total_findings != 1 else '')} detected:")
        for idx, finding in enumerate(control_flow_result.findings, 1):
            try:
                rel_path = finding.file_path.relative_to(root)
            except ValueError:
                rel_path = finding.file_path
            lines.append(f"\n    [{idx}] {rel_path}:{finding.line_number} [{finding.rule_id}]")
            lines.append(f"        Severity: {finding.severity}")
            lines.append(f"        Note:     {finding.message}")
            if finding.snippet:
                lines.append(f"        Snippet:  {finding.snippet}")
    else:
        cf_scanned = len(control_flow_result.files_scanned) if control_flow_result else file_count
        lines.append(f"  Clean: No bare excepts, swallowed exceptions, or unreachable code detected across {cf_scanned} session file{('s' if cf_scanned != 1 else '')}.")

    # 9. Mutation Verification
    lines.append("\nLocal Pre-Check Mutation Verification:")
    if result.collection_error:
        lines.append("  [!] Could not run test suite — tests failed to execute before any mutation testing began.")
        lines.append(f"  Error:  {result.collection_error}")
        lines.append("  Status: ERROR (Test suite collection failed)")
        lines.append(f"  Time:   {result.duration_seconds:.2f}s")
    elif result.total_mutants == 0:
        lines.append("  Mutants Generated: 0 (No mutable AST locations found)")
        lines.append("  Approx Score:      100.0%")
    else:
        if result.untested_files:
            status_tag = f"FAILED (0 tests collected for {len(result.untested_files)} file{('s' if len(result.untested_files) != 1 else '')})"
        elif result.mutation_score is not None and result.mutation_score < threshold:
            status_tag = f"FAILED (score {result.mutation_score:.1f}% below {threshold:.1f}%)"
        elif result.survived_mutants:
            status_tag = f"PASSED (with {len(result.survived_mutants)} surviving mutant{('s' if len(result.survived_mutants) != 1 else '')})"
        elif result.skipped_constructs:
            status_tag = f"PARTIALLY VERIFIED ({len(result.skipped_constructs)} construct{('s' if len(result.skipped_constructs) != 1 else '')} skipped)"
        else:
            status_tag = "PASSED"
        valid_count = result.killed_mutants + len(result.survived_mutants)
        if result.runner_errors:
            lines.append(
                f"  Score:  {result.mutation_score:.1f}% ({result.killed_mutants}/{valid_count} valid mutants killed, {len(result.runner_errors)} error{('s' if len(result.runner_errors) != 1 else '')} excluded)"
            )
        else:
            lines.append(f"  Score:  {result.mutation_score:.1f}% ({result.killed_mutants}/{result.total_mutants} mutants killed)")
        lines.append(f"  Status: {status_tag} (threshold: {threshold:.1f}%)")
        lines.append(f"  Time:   {result.duration_seconds:.2f}s")

    if result.untested_files:
        lines.append(f"\n[!] Untested Files ({len(result.untested_files)} file{('s' if len(result.untested_files) != 1 else '')} with 0 tests collected):")
        for f in result.untested_files:
            try:
                rel_f = f.relative_to(root)
            except ValueError:
                rel_f = f
            lines.append(f"  * {rel_f} (0 tests ran against this file - all mutations survived)")

    if result.runner_errors:
        lines.append(f"\nRunner Errors ({len(result.runner_errors)} error{('s' if len(result.runner_errors) != 1 else '')} excluded from score):")
        for mutant, err_msg in result.runner_errors:
            try:
                rel_f = mutant.file_path.relative_to(root)
            except ValueError:
                rel_f = mutant.file_path
            lines.append(f"  * {rel_f}:{mutant.line_number} [{err_msg}]")

    skipped_count = len(result.skipped_constructs)
    if result.skipped_constructs:
        lines.append(f"\nSkipped Constructs ({skipped_count} line{('s' if skipped_count != 1 else '')} skipped - not verified by Tier 1):")
        for i, s in enumerate(result.skipped_constructs, 1):
            try:
                rel_f = s.file_path.relative_to(root)
            except ValueError:
                rel_f = s.file_path
            lines.append(f"  * {rel_f}:{s.line_number} [{s.construct_name}]")
            if s.snippet:
                lines.append(f"    Code: {s.snippet}")
            lines.append(f"    Note: {s.description}")
    else:
        lines.append("\nSkipped Constructs: None (No known unsupported constructs detected)")

    pruned_eq = getattr(result, "pruned_equivalent_mutants", [])
    if pruned_eq:
        lines.append(f"\nEquivalence Pruned ({len(pruned_eq)} unkillable / dead-code mutant{('s' if len(pruned_eq) != 1 else '')} omitted from scoring):")
        for i, pe in enumerate(pruned_eq, 1):
            try:
                rel_f = pe.file_path.relative_to(root)
            except ValueError:
                rel_f = pe.file_path
            lines.append(f"  * {rel_f}:{pe.line_number} [{pe.category}] {pe.description}")
            if pe.original_line:
                lines.append(f"    Code: {pe.original_line}")

    if result.survived_mutants:
        from deployproof.synthesizer import synthesize_tests_for_surviving_mutants
        synthesized_map: Dict[str, str] = {}
        for st in synthesize_tests_for_surviving_mutants(result.survived_mutants, repo_root=root):
            synthesized_map[st.mutant_id] = st.test_code

        lines.append(f"\nSurviving Mutants ({len(result.survived_mutants)} unverified change{('s' if len(result.survived_mutants) != 1 else '')}):")
        for i, m in enumerate(result.survived_mutants, 1):
            try:
                rel_f = m.file_path.relative_to(root)
            except ValueError:
                rel_f = m.file_path
            lines.append(f"\n  [{i}] {rel_f}:{m.line_number}")
            lines.append(f"      Mutation: {m.description}")
            if m.original_line:
                lines.append(f"      Original: {m.original_line}")
            if m.mutated_line:
                lines.append(f"      Mutated:  {m.mutated_line}")
            if m.mutant_id in synthesized_map:
                indented_code = "\n".join("        " + l for l in synthesized_map[m.mutant_id].splitlines())
                lines.append(f"      Suggested Pytest Test to Kill Mutant:\n{indented_code}")
    else:
        lines.append("\nSurviving Mutants: None (All generated mutants caught by test suite)")

    lines.append("\n" + "=" * 68)
    lines.append("Notice: Local pre-check only. Full verified score runs in CI on push (via mutmut).")
    if result.collection_error:
        lines.append("Pre-check ERROR: Could not run test suite — tests failed to execute before any mutation testing began.")
        lines.append(f"  Fix environment / dependency error: {result.collection_error}")
    elif symlink_result and symlink_result.escape_findings:
        lines.append(f"SECURITY ALERT: {len(symlink_result.escape_findings)} symlink(s) escape repository sandbox. Do not approve or push.")
    elif sast_result and (sast_result.critical_count > 0 or sast_result.high_count > 0):
        lines.append(f"SECURITY ALERT: {len(sast_result.findings)} SAST vulnerability finding(s) detected. Fix security flaws before pushing.")
    elif history_secrets_result and history_secrets_result.findings:
        lines.append(f"SECURITY ALERT: {len(history_secrets_result.findings)} secret(s) found in git history. Rotate credentials immediately.")
    elif cve_result and (cve_result.critical_count > 0 or cve_result.high_count > 0):
        lines.append(f"SECURITY ALERT: {len(cve_result.advisories)} known CVE(s) found in dependencies. Upgrade affected packages.")
    elif dependency_result and dependency_result.high_risk_count > 0:
        lines.append(f"SECURITY ALERT: {dependency_result.high_risk_count} non-existent / hallucinated package(s) detected. Fix imports before pushing.")
    elif strict_mocks and mock_result and (mock_result.total_findings > 0):
        lines.append(f"Pre-check FAILED: {mock_result.total_findings} newly introduced mock(s) detected (--strict-mocks active).")
    elif strict_error_handling and control_flow_result and (control_flow_result.total_findings > 0):
        lines.append(f"Pre-check FAILED: {control_flow_result.total_findings} control flow / error handling issue(s) detected (--strict-error-handling active).")
    elif result.untested_files:
        lines.append(f"Pre-check FAILED: {len(result.untested_files)} file(s) have 0 tests. Write tests for these files before pushing.")
    elif result.mutation_score is not None and result.mutation_score < threshold:
        lines.append(f"Pre-check FAILED: Score {result.mutation_score:.1f}% is below threshold {threshold:.1f}% ({len(result.survived_mutants)} surviving mutants).")
    elif result.survived_mutants:
        lines.append(f"Pre-check PASSED ({result.mutation_score:.1f}% >= {threshold:.1f}%), with {len(result.survived_mutants)} surviving mutant(s) flagged.")
    elif result.skipped_constructs:
        lines.append(f"Pre-check passed on basic operators, but {skipped_count} unsupported construct(s) were skipped. Run in CI for full verification.")
    else:
        lines.append("Pre-check clean: 100% of tested basic mutations caught.")
    return "\n".join(lines)