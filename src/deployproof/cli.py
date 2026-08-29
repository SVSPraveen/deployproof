"""Command-line interface for DeployProof."""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from deployproof import __version__
from deployproof.dependencies import (
    extract_all_new_dependencies,
    scan_dependencies,
)
from deployproof.control_flow import scan_session_files_for_control_flow
from deployproof.diff import (
    DiffScopeError,
    InvalidBaseRefError,
    NotAGitRepositoryError,
    get_git_root,
    is_test_file,
    resolve_changed_python_files,
    resolve_changed_session_files,
)
from deployproof.mocks import scan_session_files_for_mocks
from deployproof.mutator import run_mutation_tests
from deployproof.reporter import LARGE_FILE_LOC_THRESHOLD, format_json_report, format_report
from deployproof.secrets import scan_session_files_for_secrets
from deployproof.symlinks import scan_session_files_for_symlinks
from deployproof.wsl import check_wsl_readiness, run_wsl_mutmut


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

    # 'check' command for V1 scope
    check_parser = subparsers.add_parser(
        "check",
        help="Run deployability verification checks against session changes.",
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
        default=80.0,
        help="Minimum mutation score percentage to pass (default: 80.0).",
    )
    check_parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Test runner timeout in seconds per mutant (default: 10.0).",
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
        default=False,
        help="Fail the verification gate if new mock or monkeypatch usage is introduced in test files.",
    )
    check_parser.add_argument(
        "--strict-error-handling",
        action="store_true",
        default=False,
        help="Fail the verification gate if bare excepts, swallowed exceptions, or unreachable code are detected.",
    )
    check_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output check results as a structured JSON object.",
    )

    # Placeholder 'init' command
    subparsers.add_parser(
        "init",
        help="Initialize DeployProof configuration in the current repository.",
    )

    return parser


def handle_check(args: argparse.Namespace) -> int:
    """Handle the 'check' subcommand."""
    cwd = Path.cwd().resolve()
    repo_root: Optional[Path] = None

    try:
        if args.files:
            session_files = [Path(f).resolve() for f in args.files]
            if session_files:
                try:
                    repo_root = get_git_root(session_files[0].parent)
                except DiffScopeError:
                    repo_root = session_files[0].parent
            else:
                repo_root = cwd
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
                            "threshold": args.threshold,
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
                            "strict_mocks_active": getattr(args, "strict_mocks", False),
                            "strict_mocks_triggered": False,
                            "strict_error_handling_active": getattr(args, "strict_error_handling", False),
                            "strict_error_handling_triggered": False,
                        },
                        "control_flow": {
                            "clean": True,
                            "strict_gate_triggered": False,
                            "findings": [],
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

    # 1. Run Symlink & Sandbox Escape Scanner across all session files
    symlink_result = scan_session_files_for_symlinks(session_files, repo_root=repo_root or cwd)

    # 2. Run Secrets & Credentials Scanner across all session files
    secrets_result = scan_session_files_for_secrets(session_files)

    # 3. Run Slopsquatting & Dependency Hallucination Scanner across session files
    extracted_deps = extract_all_new_dependencies(session_files, root=repo_root or cwd, base=args.base)
    dependency_result = scan_dependencies(extracted_deps)

    # 4. Run Mock Usage Detector across session test files
    mock_result = scan_session_files_for_mocks(
        session_files=session_files,
        root=repo_root or cwd,
        base=args.base,
    )

    # 5. Run Control Flow & Swallowed Exception Scanner across session files
    control_flow_result = scan_session_files_for_control_flow(
        session_files=session_files,
        root=repo_root or cwd,
        base=args.base,
    )

    # 6. Filter target Python files for mutation testing
    if args.files:
        non_test_files = [f for f in session_files if f.is_file() and f.suffix == ".py" and not is_test_file(f)]
        target_files = non_test_files if non_test_files else [f for f in session_files if f.is_file() and f.suffix == ".py"]
    else:
        target_files = [f for f in session_files if f.is_file() and f.suffix == ".py" and not is_test_file(f)]

    # Notify upfront if large files are in scope (only in text mode)
    if not getattr(args, "json", False):
        for f in target_files:
            try:
                loc = len(f.read_text(encoding="utf-8", errors="replace").splitlines())
                if loc >= LARGE_FILE_LOC_THRESHOLD:
                    try:
                        rel = f.relative_to(repo_root or cwd)
                    except ValueError:
                        rel = f
                    print(
                        f"Notice: Large file '{rel}' ({loc} LOC) detected - mutation testing may take several minutes."
                    )
            except Exception:
                pass

    # Optional WSL delegation
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
                    or dependency_result.high_risk_count > 0
                    or (getattr(args, "strict_mocks", False) and mock_result.total_findings > 0)
                    or (getattr(args, "strict_error_handling", False) and control_flow_result.total_findings > 0)
                )
                return 1 if has_security_issue else 0
            else:
                if not getattr(args, "json", False):
                    print(f"WSL execution error: {wsl_res.get('error') or wsl_res.get('stderr')}", file=sys.stderr)
                    print("Falling back to Tier 1 local pre-check...")
        else:
            if not getattr(args, "json", False):
                print(wsl_msg)
                print("-" * 68)

    result = run_mutation_tests(
        target_files=target_files,
        repo_root=repo_root or cwd,
        test_runner_timeout=args.timeout,
        extra_pytest_args=args.tests,
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
            strict_mocks=getattr(args, "strict_mocks", False),
            strict_error_handling=getattr(args, "strict_error_handling", False),
            repo_root=repo_root or cwd,
            threshold=args.threshold,
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
            strict_mocks=getattr(args, "strict_mocks", False),
            strict_error_handling=getattr(args, "strict_error_handling", False),
            repo_root=repo_root or cwd,
            threshold=args.threshold,
        )
    print(report_text)

    # Fail if mutation score threshold not met, secrets detected, symlink sandbox escapes found, hallucinated packages detected, or strict flags triggered
    strict_mocks_triggered = bool(getattr(args, "strict_mocks", False) and mock_result.total_findings > 0)
    strict_error_triggered = bool(
        getattr(args, "strict_error_handling", False) and control_flow_result.total_findings > 0
    )
    if (
        result.mutation_score < args.threshold
        or len(result.untested_files) > 0
        or len(secrets_result.findings) > 0
        or len(symlink_result.escape_findings) > 0
        or dependency_result.high_risk_count > 0
        or strict_mocks_triggered
        or strict_error_triggered
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

    # 1. Create or verify configuration file (.deployproof.json)
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
        }
        config_path.write_text(json.dumps(default_config, indent=2) + "\n", encoding="utf-8")
        print(f"  [+] Created configuration file: {config_path.name}")
    else:
        print(f"  [.] Configuration file already exists: {config_path.name}")

    # 2. Install / verify git pre-push hook if inside git repo
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
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(errors="replace")
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
