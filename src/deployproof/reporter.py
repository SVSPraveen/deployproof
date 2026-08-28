"""Terminal output reporter for DeployProof."""

from pathlib import Path
from typing import List, Optional
from deployproof.mutator import MutationResult
from deployproof.secrets import SecretsScanResult
from deployproof.symlinks import SymlinkScanResult

LARGE_FILE_LOC_THRESHOLD = 300


def format_report(
    result: MutationResult,
    target_files: List[Path],
    secrets_result: Optional[SecretsScanResult] = None,
    symlink_result: Optional[SymlinkScanResult] = None,
    repo_root: Optional[Path] = None,
    threshold: float = 80.0,
) -> str:
    """Format mutation testing results, secrets scan, and symlink escape checks as terminal output."""
    lines: List[str] = []
    lines.append("DeployProof — LOCAL PRE-CHECK (approximate) — not the verified score")
    lines.append("=" * 68)

    root = (repo_root or Path.cwd()).resolve()

    # Scope section
    file_count = len(target_files)
    lines.append(f"\nTarget Scope ({file_count} file{'s' if file_count != 1 else ''} evaluated):")
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
                lines.append(
                    f"  • {rel} ({loc} LOC) — [!] Large file: pre-check may take several minutes. Parallelization not yet implemented."
                )
            else:
                lines.append(f"  • {rel}")
    else:
        lines.append("  (No modified Python files in scope)")

    # Symlink & Sandbox Escape Scan section
    lines.append("\nSymlink & Sandbox Escape Scan (CWE-61/CWE-451):")
    if symlink_result and symlink_result.escape_findings:
        escape_count = len(symlink_result.escape_findings)
        lines.append(
            f"  [!] {escape_count} sandbox-escape symlink{'s' if escape_count != 1 else ''} detected:"
        )
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
            f"  Clean: No sandbox-escape symlinks detected across {symlink_result.files_scanned} session files ({safe_count} safe in-repo symlink{'s' if safe_count != 1 else ''} verified)."
        )
    else:
        scanned_count = symlink_result.files_scanned if symlink_result else file_count
        lines.append(
            f"  Clean: No symlinks or sandbox-escape traversal links detected across {scanned_count} session file{'s' if scanned_count != 1 else ''}."
        )

    # Secrets scan section
    lines.append("\nSecrets & Credentials Pre-Push Scan:")
    if secrets_result and secrets_result.findings:
        findings_count = len(secrets_result.findings)
        lines.append(
            f"  [!] {findings_count} potential secret/credential finding{'s' if findings_count != 1 else ''} detected:"
        )
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
        lines.append(
            f"  Clean: No hardcoded secrets or tracked .env files detected across {scanned_count} session file{'s' if scanned_count != 1 else ''}."
        )

    # Score section
    lines.append("\nLocal Pre-Check Mutation Verification:")
    if result.total_mutants == 0:
        lines.append("  Mutants Generated: 0 (No mutable AST locations found)")
        lines.append("  Approx Score:      100.0%")
    else:
        if result.untested_files:
            status_tag = f"FAILED (0 tests collected for {len(result.untested_files)} file{'s' if len(result.untested_files) != 1 else ''})"
        elif result.survived_mutants:
            status_tag = "FAILED"
        elif result.skipped_constructs:
            status_tag = f"PARTIALLY VERIFIED ({len(result.skipped_constructs)} construct{'s' if len(result.skipped_constructs) != 1 else ''} skipped)"
        else:
            status_tag = "PASSED"

        lines.append(
            f"  Score:  {result.mutation_score:.1f}% ({result.killed_mutants}/{result.total_mutants} mutants killed)"
        )
        lines.append(f"  Status: {status_tag} (threshold: {threshold:.1f}%)")
        lines.append(f"  Time:   {result.duration_seconds:.2f}s")

    # Untested files warning section
    if result.untested_files:
        lines.append(
            f"\n[!] Untested Files ({len(result.untested_files)} file{'s' if len(result.untested_files) != 1 else ''} with 0 tests collected):"
        )
        for f in result.untested_files:
            try:
                rel_f = f.relative_to(root)
            except ValueError:
                rel_f = f
            lines.append(f"  • {rel_f} (0 tests ran against this file — all mutations survived)")

    # Runner errors section
    if result.runner_errors:
        lines.append(
            f"\nRunner Errors ({len(result.runner_errors)} error{'s' if len(result.runner_errors) != 1 else ''} excluded from score):"
        )
        for mutant, err_msg in result.runner_errors:
            try:
                rel_f = mutant.file_path.relative_to(root)
            except ValueError:
                rel_f = mutant.file_path
            lines.append(f"  • {rel_f}:{mutant.line_number} [{err_msg}]")

    # Skipped Constructs Section (Always shown alongside score)
    skipped_count = len(result.skipped_constructs)
    if result.skipped_constructs:
        lines.append(
            f"\nSkipped Constructs ({skipped_count} line{'s' if skipped_count != 1 else ''} skipped — not verified by Tier 1):"
        )
        for i, s in enumerate(result.skipped_constructs, 1):
            try:
                rel_f = s.file_path.relative_to(root)
            except ValueError:
                rel_f = s.file_path
            lines.append(f"  • {rel_f}:{s.line_number} [{s.construct_name}]")
            if s.snippet:
                lines.append(f"    Code: {s.snippet}")
            lines.append(f"    Note: {s.description}")
    else:
        lines.append("\nSkipped Constructs: None (No known unsupported constructs detected)")

    # Surviving mutants section
    if result.survived_mutants:
        lines.append(
            f"\nSurviving Mutants ({len(result.survived_mutants)} unverified change{'s' if len(result.survived_mutants) != 1 else ''}):"
        )
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
    else:
        lines.append("\nSurviving Mutants: None (All generated mutants caught by test suite)")

    lines.append("\n" + "=" * 68)
    lines.append("Notice: Local pre-check only. Full verified score runs in CI on push (via mutmut).")
    if symlink_result and symlink_result.escape_findings:
        lines.append(
            f"SECURITY ALERT: {len(symlink_result.escape_findings)} symlink(s) escape repository sandbox. Do not approve or push."
        )
    elif result.untested_files:
        lines.append(
            f"Pre-check FAILED: {len(result.untested_files)} file(s) have 0 tests. Write tests for these files before pushing."
        )
    elif result.survived_mutants:
        lines.append(
            f"Pre-check flagged {len(result.survived_mutants)} surviving mutant(s). Write tests covering these lines before pushing."
        )
    elif result.skipped_constructs:
        lines.append(
            f"Pre-check passed on basic operators, but {skipped_count} unsupported construct(s) were skipped. Run in CI for full verification."
        )
    else:
        lines.append("Pre-check clean: 100% of tested basic mutations caught.")

    return "\n".join(lines)
