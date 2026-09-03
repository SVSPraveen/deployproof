"""Command-line interface for DeployProof."""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from deployproof import __version__
from deployproof.control_flow import scan_session_files_for_control_flow
from deployproof.cve import scan_dependencies_for_cves
from deployproof.dependencies import extract_all_new_dependencies, scan_dependencies
from deployproof.diff import (
    DiffScopeError,
    InvalidBaseRefError,
    NotAGitRepositoryError,
    get_git_root,
    is_excluded_mutation_target,
    is_test_file,
    resolve_changed_python_files,
    resolve_changed_session_files,
    resolve_full_repo_session_files,
)
from deployproof.history_secrets import scan_git_history_for_secrets
from deployproof.mocks import scan_session_files_for_mocks
from deployproof.mutator import cleanup_stale_deployproof_temp_dirs, run_mutation_tests
from deployproof.reporter import LARGE_FILE_LOC_THRESHOLD, format_json_report, format_report
from deployproof.sast import scan_session_files_for_sast
from deployproof.secrets import scan_session_files_for_secrets
from deployproof.symlinks import scan_session_files_for_symlinks
from deployproof.wsl import check_wsl_readiness, run_wsl_mutmut


def load_repo_config(root: Optional[Path]) -> dict:
    """
    Load configuration from pyproject.toml [tool.deployproof] and .deployproof.json.

    Precedence:
      1. .deployproof.json (if present, merges/overrides pyproject.toml)
      2. pyproject.toml [tool.deployproof] table
      3. Built-in defaults
    """
    if not root:
        return {}
    merged_config: dict = {}
    curr = root.resolve()
    candidates = [curr]
    for p in curr.parents:
        if (p / ".git").is_dir() or (p / "pyproject.toml").is_file() or (p / ".deployproof.json").is_file():
            candidates.append(p)
            break
    for candidate in reversed(candidates):
        pyproject_path = candidate / "pyproject.toml"
        if pyproject_path.is_file():
            try:
                try:
                    import tomllib
                except ImportError:
                    try:
                        import tomli as tomllib
                    except ImportError:
                        tomllib = None
                if tomllib is not None:
                    toml_data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
                    tool_table = toml_data.get("tool", {}).get("deployproof", {})
                    if isinstance(tool_table, dict):
                        merged_config.update(tool_table)
            except Exception:
                pass
        config_path = candidate / ".deployproof.json"
        if config_path.is_file():
            try:
                import json
                json_data = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(json_data, dict):
                    merged_config.update(json_data)
            except Exception:
                pass
    return merged_config


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="deployproof",
        description="DeployProof: A deterministic AI-code deployability checker.",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show program's version number and exit.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    check_parser = subparsers.add_parser(
        "check",
        help="Run deployability verification checks against session changes.",
    )
    check_parser.add_argument(
        "--full-repo",
        action="store_true",
        default=False,
        help="Scan all files in repository respecting .gitignore instead of diff-scoped session files.",
    )
    check_parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel worker processes for mutation scans (default: auto, up to 8).",
    )
    check_parser.add_argument(
        "--base",
        type=str,
        default=None,
        help="Base git ref (branch/commit/tag) to diff against.",
    )
    check_parser.add_argument(
        "--files",
        nargs="+",
        type=str,
        default=None,
        help="Explicit files to evaluate (bypasses git diff).",
    )
    check_parser.add_argument(
        "--tests",
        nargs="+",
        type=str,
        default=None,
        help="Specific test file(s) or directories to execute.",
    )
    check_parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Minimum mutation score percentage to pass (default: 80.0, or from .deployproof.json).",
    )
    check_parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Test runner timeout in seconds per mutant (default: 10.0, or from .deployproof.json).",
    )
    check_parser.add_argument(
        "--wsl",
        action="store_true",
        default=False,
        help="Delegate mutation testing to mutmut inside WSL (Windows only).",
    )
    check_parser.add_argument(
        "--strict-mocks",
        action="store_true",
        default=None,
        help="Fail the verification gate if new mock or monkeypatch usage is introduced in test files.",
    )
    check_parser.add_argument(
        "--strict-error-handling",
        action="store_true",
        default=None,
        help="Fail the verification gate if bare excepts, swallowed exceptions, or unreachable code are detected.",
    )
    check_parser.add_argument(
        "--sast",
        action="store_true",
        default=True,
        help="Enable AST SAST security scanner for OWASP Top 10 vulnerabilities (default: True).",
    )
    check_parser.add_argument(
        "--scan-git-history",
        action="store_true",
        default=True,
        help="Scan past git commit history for leaked credentials (default: True).",
    )
    check_parser.add_argument(
        "--history-depth",
        type=int,
        default=50,
        help="Number of past commits to scan for historical secrets (default: 50).",
    )
    check_parser.add_argument(
        "--check-cve",
        action="store_true",
        default=True,
        help="Cross-reference dependencies against OSV CVE database (default: True).",
    )
    check_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output check results as a structured JSON object.",
    )
    check_parser.add_argument(
        "--generate-tests",
        "--heal-tests",
        nargs="?",
        const="tests/test_deployproof_healed.py",
        default=None,
        metavar="OUTPUT_FILE",
        help="Synthesize and save ready-to-run pytest unit tests to kill surviving mutants (default: tests/test_deployproof_healed.py).",
    )
    check_parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        default=False,
        help="Prompt interactively to apply auto-synthesized test cases to kill surviving mutants.",
    )
    check_parser.add_argument(
        "--suggest-tests",
        action="store_true",
        default=False,
        help="Print auto-synthesized test suggestions inline for surviving mutants in terminal report.",
    )
    check_parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        metavar="PATH",
        help="Custom file path to save the full verification report (default: .deployproof/report.txt).",
    )
    check_parser.add_argument(
        "--github-actions",
        "--ci",
        action="store_true",
        default=False,
        help="Emit GitHub Actions workflow annotations and step summary markdown ($GITHUB_STEP_SUMMARY).",
    )

    subparsers.add_parser(
        "init",
        help="Initialize DeployProof configuration in the current repository.",
    )

    return parser


def handle_check(args: argparse.Namespace) -> int:
    """Handle the 'check' subcommand."""
    cleanup_stale_deployproof_temp_dirs()
    cwd = Path.cwd().resolve()
    repo_root: Optional[Path] = None
    is_full_repo = getattr(args, "full_repo", False)

    try:
        if args.files:
            session_files = [
                (cwd / f).absolute() if not Path(f).is_absolute() else Path(f)
                for f in args.files
            ]
            if session_files:
                try:
                    repo_root = get_git_root(session_files[0].parent)
                except DiffScopeError:
                    repo_root = session_files[0].parent
            else:
                repo_root = cwd
        elif is_full_repo:
            try:
                repo_root = get_git_root(cwd)
            except DiffScopeError:
                repo_root = cwd
            if not getattr(args, "json", False):
                print(
                    "Notice: Full repo scan active — evaluating all repository files (this may take significantly longer than a diff-scoped check).\n"
                )
            session_files = resolve_full_repo_session_files(cwd=cwd)
        else:
            repo_root = get_git_root(cwd)
            session_files = resolve_changed_session_files(cwd=cwd, base=args.base)
    except NotAGitRepositoryError:
        print("Error: Not a git repository. Initialize git or specify files with --files.", file=sys.stderr)
        return 1
    except InvalidBaseRefError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except DiffScopeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    cfg = load_repo_config(repo_root or cwd)
    threshold = args.threshold if args.threshold is not None else float(cfg.get("threshold", 80.0))
    timeout = args.timeout if args.timeout is not None else float(cfg.get("timeout", 10.0))
    strict_mocks = args.strict_mocks if args.strict_mocks is not None else bool(cfg.get("strict_mocks", False))
    strict_error_handling = args.strict_error_handling if args.strict_error_handling is not None else bool(cfg.get("strict_error_handling", False))
    secrets_enabled = bool(cfg.get("secrets_scanning", True))
    symlinks_enabled = bool(cfg.get("symlink_scanning", True))
    dependencies_enabled = bool(cfg.get("dependency_scanning", True))
    sast_enabled = getattr(args, "sast", True) and bool(cfg.get("sast_scanning", True))
    history_secrets_enabled = getattr(args, "scan_git_history", True) and bool(cfg.get("history_secrets_scanning", True))
    cve_enabled = getattr(args, "check_cve", True) and bool(cfg.get("cve_scanning", True))

    if not session_files:
        if getattr(args, "json", False):
            import json

            print(
                json.dumps(
                    {
                        "version": __version__,
                        "status": "passed",
                        "message": "No modified files detected in current session.",
                        "scope": {"target_files": []},
                        "summary": {
                            "target_files_count": 0,
                            "mutation_score": 100.0,
                            "threshold": threshold,
                            "secrets_found": 0,
                            "symlink_escapes_found": 0,
                            "dependency_findings": {
                                "high_risk": 0,
                                "medium_risk": 0,
                                "ok": 0,
                                "unknown": 0,
                                "unscanned": 0,
                            },
                            "mock_usages_found": 0,
                            "control_flow_findings": 0,
                            "sast_findings": 0,
                            "history_secrets_found": 0,
                            "cve_advisories_found": 0,
                            "strict_mocks_active": strict_mocks,
                            "strict_mocks_triggered": False,
                            "strict_error_handling_active": strict_error_handling,
                            "strict_error_handling_triggered": False,
                        },
                    },
                    indent=2,
                )
            )
            return 0
        else:
            print("DeployProof: No modified files detected in current session.")
            print("Working tree is clean. Use --base <ref> or --files <path...> to evaluate specific files.")
            return 0

    if symlinks_enabled:
        symlink_result = scan_session_files_for_symlinks(session_files, repo_root=repo_root or cwd)
    else:
        from deployproof.symlinks import SymlinkScanSummary

        symlink_result = SymlinkScanSummary(total_scanned=0, safe_count=0, escape_findings=[], duration_seconds=0.0)

    if secrets_enabled:
        secrets_result = scan_session_files_for_secrets(session_files)
    else:
        from deployproof.secrets import SecretScanSummary

        secrets_result = SecretScanSummary(total_files_scanned=0, findings=[], duration_seconds=0.0)

    if history_secrets_enabled and repo_root:
        history_secrets_result = scan_git_history_for_secrets(
            repo_root=repo_root or cwd,
            max_commits=getattr(args, "history_depth", 50),
        )
    else:
        history_secrets_result = None

    if sast_enabled:
        sast_result = scan_session_files_for_sast(session_files)
    else:
        sast_result = None

    if dependencies_enabled:
        extracted_deps = extract_all_new_dependencies(session_files, root=repo_root or cwd, base=args.base, full_repo=is_full_repo)
        dependency_result = scan_dependencies(extracted_deps)
    else:
        from deployproof.dependencies import DependencyScanSummary

        extracted_deps = []
        dependency_result = DependencyScanSummary(
            total_scanned=0,
            high_risk_count=0,
            medium_risk_count=0,
            ok_count=0,
            unknown_count=0,
            findings=[],
            duration_seconds=0.0,
            unscanned_count=0,
        )

    if cve_enabled and extracted_deps:
        cve_result = scan_dependencies_for_cves(extracted_deps)
    else:
        cve_result = None

    mock_result = scan_session_files_for_mocks(
        session_files=session_files,
        root=repo_root or cwd,
        base=args.base,
        full_repo=is_full_repo,
    )
    control_flow_result = scan_session_files_for_control_flow(
        session_files=session_files,
        root=repo_root or cwd,
        base=args.base,
        full_repo=is_full_repo,
    )

    if args.files:
        non_excluded_files = [
            f
            for f in session_files
            if f.is_file() and f.suffix == ".py" and not is_excluded_mutation_target(f, repo_root or cwd)
        ]
        target_files = non_excluded_files if non_excluded_files else [f for f in session_files if f.is_file() and f.suffix == ".py"]
    else:
        target_files = [
            f
            for f in session_files
            if f.is_file() and f.suffix == ".py" and not is_excluded_mutation_target(f, repo_root or cwd)
        ]

    if not getattr(args, "json", False):
        for f in target_files:
            try:
                loc = len(f.read_text(encoding="utf-8", errors="replace").splitlines())
                if loc >= LARGE_FILE_LOC_THRESHOLD:
                    try:
                        rel = f.relative_to(repo_root or cwd)
                    except ValueError:
                        rel = f
                    print(f"Notice: Large file '{rel}' ({loc} LOC) detected - mutation testing may take several minutes.")
            except Exception:
                pass

    if getattr(args, "wsl", False):
        wsl_ready, wsl_msg = check_wsl_readiness()
        if wsl_ready:
            if not getattr(args, "json", False):
                print("DeployProof - Delegating to mutmut in WSL...")
            wsl_res = run_wsl_mutmut(repo_root or cwd, target_files)
            if wsl_res.get("success"):
                if not getattr(args, "json", False):
                    print(wsl_res.get("stdout", ""))
                has_security_issue = bool(
                    secrets_result.findings
                    or symlink_result.escape_findings
                    or (dependency_result.high_risk_count > 0)
                    or (strict_mocks and mock_result.total_findings > 0)
                    or (strict_error_handling and control_flow_result.total_findings > 0)
                    or (sast_result and (sast_result.critical_count > 0 or sast_result.high_count > 0))
                    or (history_secrets_result and not history_secrets_result.clean)
                    or (cve_result and (cve_result.critical_count > 0 or cve_result.high_count > 0))
                )
                return 1 if has_security_issue else 0
            elif not getattr(args, "json", False):
                print(f"WSL execution error: {wsl_res.get('error') or wsl_res.get('stderr')}", file=sys.stderr)
                print("Falling back to Tier 1 local pre-check...")
        elif not getattr(args, "json", False):
            print(wsl_msg)
            print("-" * 68)

    req_workers = getattr(args, "workers", None)
    if req_workers is not None:
        workers = max(1, req_workers)
    elif is_full_repo:
        workers = 8
    else:
        workers = None

    result = run_mutation_tests(
        target_files=target_files,
        repo_root=repo_root or cwd,
        test_runner_timeout=timeout,
        extra_pytest_args=args.tests,
        workers=workers,
        is_full_repo=is_full_repo,
        base=args.base,
        quiet=getattr(args, "json", False),
    )

    if getattr(args, "json", False):
        report_text = format_json_report(
            result=result,
            target_files=target_files,
            secrets_result=secrets_result,
            symlink_result=symlink_result,
            dependency_result=dependency_result,
            mock_result=mock_result,
            control_flow_result=control_flow_result,
            sast_result=sast_result,
            history_secrets_result=history_secrets_result,
            cve_result=cve_result,
            strict_mocks=strict_mocks,
            strict_error_handling=strict_error_handling,
            repo_root=repo_root or cwd,
            threshold=threshold,
            version=__version__,
        )
    else:
        report_text = format_report(
            result=result,
            target_files=target_files,
            secrets_result=secrets_result,
            symlink_result=symlink_result,
            dependency_result=dependency_result,
            mock_result=mock_result,
            control_flow_result=control_flow_result,
            sast_result=sast_result,
            history_secrets_result=history_secrets_result,
            cve_result=cve_result,
            strict_mocks=strict_mocks,
            strict_error_handling=strict_error_handling,
            repo_root=repo_root or cwd,
            threshold=threshold,
            suggest_tests=getattr(args, "suggest_tests", False),
        )

    # Automatically save full report to persistent artifact file (.deployproof/report.txt or custom --output)
    try:
        custom_output = getattr(args, "output", None)
        if custom_output:
            report_path = (repo_root or cwd) / Path(custom_output)
            report_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            report_dir = (repo_root or cwd) / ".deployproof"
            report_dir.mkdir(parents=True, exist_ok=True)
            report_filename = "report.json" if getattr(args, "json", False) else "report.txt"
            report_path = report_dir / report_filename

        report_path.write_text(report_text, encoding="utf-8")
        try:
            rel_report_path = report_path.relative_to(repo_root or cwd)
        except ValueError:
            rel_report_path = report_path

        if not getattr(args, "json", False):
            report_text += f"\n[+] Full report saved to: {rel_report_path}\n"
    except Exception:
        pass

    print(report_text)

    generate_tests_path = getattr(args, "generate_tests", None)
    if generate_tests_path and result.survived_mutants:
        from deployproof.synthesizer import synthesize_tests_for_surviving_mutants

        synth_tests = synthesize_tests_for_surviving_mutants(
            result.survived_mutants,
            repo_root=repo_root or cwd,
        )
        if synth_tests:
            out_file = (repo_root or cwd) / Path(generate_tests_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            header = '"""\nAuto-generated unit tests synthesized by DeployProof to kill surviving mutants.\nRun pytest on this file to verify that all surviving mutants are killed.\n"""\nimport os\nimport sys\nfrom pathlib import Path\nimport pytest\n\n# Ensure src/ and repo root are in python search path\n_root = Path(__file__).resolve().parent.parent\nfor _p in [str(_root / "src"), str(_root)]:\n    if _p not in sys.path:\n        sys.path.insert(0, _p)\n\n'
            content = header + "\n\n".join(st.test_code for st in synth_tests) + "\n"
            out_file.write_text(content, encoding="utf-8")
            if not getattr(args, "json", False):
                try:
                    rel_out = out_file.relative_to(repo_root or cwd)
                except ValueError:
                    rel_out = out_file
                print(f"\n[+] DeployProof Synthesized {len(synth_tests)} self-healing test(s) in {rel_out}!")
                print(f"    Run 'pytest {rel_out}' to execute and kill surviving mutants.\n")

    is_interactive = getattr(args, "interactive", False) or bool(cfg.get("interactive", False))
    if is_interactive and result.survived_mutants and not getattr(args, "json", False):
        from deployproof.interactive import prompt_apply_synthesized_tests

        prompt_apply_synthesized_tests(
            surviving_mutants=result.survived_mutants,
            repo_root=repo_root or cwd,
            output_file_override=((repo_root or cwd) / Path(generate_tests_path)) if generate_tests_path else None,
        )

    from deployproof.ci import (
        format_github_annotations,
        format_github_step_summary,
        is_github_actions,
        write_github_step_summary_if_enabled,
    )

    should_emit_gh = getattr(args, "github_actions", False) or is_github_actions()
    if should_emit_gh:
        if not getattr(args, "json", False):
            gh_annotations = format_github_annotations(
                result=result,
                target_files=target_files,
                secrets_result=secrets_result,
                symlink_result=symlink_result,
                dependency_result=dependency_result,
                mock_result=mock_result,
                control_flow_result=control_flow_result,
                sast_result=sast_result,
                history_secrets_result=history_secrets_result,
                cve_result=cve_result,
                repo_root=repo_root or cwd,
            )
            for ann in gh_annotations:
                print(ann)
        gh_summary_md = format_github_step_summary(
            result=result,
            target_files=target_files,
            secrets_result=secrets_result,
            symlink_result=symlink_result,
            dependency_result=dependency_result,
            mock_result=mock_result,
            control_flow_result=control_flow_result,
            sast_result=sast_result,
            history_secrets_result=history_secrets_result,
            cve_result=cve_result,
            strict_mocks=strict_mocks,
            strict_error_handling=strict_error_handling,
            repo_root=repo_root or cwd,
            threshold=threshold,
        )
        write_github_step_summary_if_enabled(gh_summary_md)

    if result.collection_error:
        return 2

    strict_mocks_triggered = bool(strict_mocks and mock_result.total_findings > 0)
    strict_error_triggered = bool(strict_error_handling and control_flow_result.total_findings > 0)
    sast_triggered = bool(sast_result and (sast_result.critical_count > 0 or sast_result.high_count > 0))
    history_secrets_triggered = bool(history_secrets_result and not history_secrets_result.clean)
    cve_triggered = bool(cve_result and (cve_result.critical_count > 0 or cve_result.high_count > 0))

    if (
        (result.mutation_score is not None and result.mutation_score < threshold)
        or len(result.untested_files) > 0
        or len(secrets_result.findings) > 0
        or len(symlink_result.escape_findings) > 0
        or (dependency_result.high_risk_count > 0)
        or strict_mocks_triggered
        or strict_error_triggered
        or sast_triggered
        or history_secrets_triggered
        or cve_triggered
    ):
        return 1

    return 0


def handle_init(args: argparse.Namespace) -> int:
    """Handle the 'init' subcommand to initialize configuration and git hooks."""
    cwd = Path.cwd().resolve()
    try:
        repo_root = get_git_root(cwd)
    except DiffScopeError:
        repo_root = cwd

    print(f"DeployProof: Initializing in {repo_root}...")
    config_path = repo_root / ".deployproof.json"
    if not config_path.exists():
        import json

        default_config = {
            "version": __version__,
            "threshold": 80.0,
            "timeout": 10.0,
            "secrets_scanning": True,
            "symlink_scanning": True,
            "dependency_scanning": True,
            "sast_scanning": True,
            "history_secrets_scanning": True,
            "cve_scanning": True,
        }
        config_path.write_text(json.dumps(default_config, indent=2) + "\n", encoding="utf-8")
        print(f"  [+] Created configuration file: {config_path.name}")
    else:
        print(f"  [.] Configuration file already exists: {config_path.name}")

    hooks_dir = repo_root / ".git" / "hooks"
    if hooks_dir.is_dir():
        pre_push_hook = hooks_dir / "pre-push"
        hook_script = "#!/usr/bin/env sh\n# DeployProof deterministic pre-push verification gate\ndeployproof check\n"
        pre_push_hook.write_text(hook_script, encoding="utf-8")
        try:
            import stat

            pre_push_hook.chmod(pre_push_hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except Exception:
            pass
        print("  [+] Installed git pre-push hook: .git/hooks/pre-push")
    else:
        print("  [i] Note: .git/hooks directory not found. Initialize git to enable automatic pre-push gating.")

    print("\nDeployProof initialization complete. Run 'deployproof check' to verify your session changes.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point for the DeployProof CLI."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(line_buffering=True, errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(line_buffering=False, errors="replace")
        except Exception:
            pass
    parser = create_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.command == "check":
        return handle_check(args)
    elif args.command == "init":
        return handle_init(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())