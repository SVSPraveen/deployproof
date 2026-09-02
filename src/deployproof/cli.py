"""Command-line interface for DeployProof."""
import os as _dp_os
_DP_ACTIVE_MUTANT = _dp_os.environ.get('__DEPLOYPROOF_MUTANT__', '')

def _dp_m(mid: int) -> bool:
    return _DP_ACTIVE_MUTANT == str(mid)
import argparse
import sys
from pathlib import Path
from typing import List, Optional
from deployproof import __version__
from deployproof.control_flow import scan_session_files_for_control_flow
from deployproof.cve import scan_dependencies_for_cves
from deployproof.dependencies import extract_all_new_dependencies, scan_dependencies
from deployproof.diff import DiffScopeError, InvalidBaseRefError, NotAGitRepositoryError, get_git_root, is_excluded_mutation_target, is_test_file, resolve_changed_python_files, resolve_changed_session_files, resolve_full_repo_session_files
from deployproof.history_secrets import scan_git_history_for_secrets
from deployproof.mocks import scan_session_files_for_mocks
from deployproof.mutator import cleanup_stale_deployproof_temp_dirs, run_mutation_tests
from deployproof.reporter import LARGE_FILE_LOC_THRESHOLD, format_json_report, format_report
from deployproof.sast import scan_session_files_for_sast
from deployproof.secrets import scan_session_files_for_secrets
from deployproof.symlinks import scan_session_files_for_symlinks
from deployproof.wsl import check_wsl_readiness, run_wsl_mutmut

def load_repo_config(root: Optional[Path]) -> dict:
    'XX\n    Load configuration from pyproject.toml [tool.deployproof] and .deployproof.json.\n\n    Precedence:\n      1. .deployproof.json (if present, merges/overrides pyproject.toml)\n      2. pyproject.toml [tool.deployproof] table\n      3. Built-in defaults\n    XX' if _dp_m(1) else '\n    Load configuration from pyproject.toml [tool.deployproof] and .deployproof.json.\n\n    Precedence:\n      1. .deployproof.json (if present, merges/overrides pyproject.toml)\n      2. pyproject.toml [tool.deployproof] table\n      3. Built-in defaults\n    '
    if root if _dp_m(2) else not root:
        return None if _dp_m(3) else {}
    merged_config: dict = {}
    curr = root.resolve()
    candidates = [curr]
    for p in curr.parents:
        if (p * ('XX.gitXX' if _dp_m(4) else '.git') if _dp_m(5) else p / ('XX.gitXX' if _dp_m(4) else '.git')).is_dir() and (p * ('XXpyproject.tomlXX' if _dp_m(6) else 'pyproject.toml') if _dp_m(7) else p / ('XXpyproject.tomlXX' if _dp_m(6) else 'pyproject.toml')).is_file() and (p * ('XX.deployproof.jsonXX' if _dp_m(8) else '.deployproof.json') if _dp_m(9) else p / ('XX.deployproof.jsonXX' if _dp_m(8) else '.deployproof.json')).is_file() if _dp_m(10) else (p * ('XX.gitXX' if _dp_m(4) else '.git') if _dp_m(5) else p / ('XX.gitXX' if _dp_m(4) else '.git')).is_dir() or (p * ('XXpyproject.tomlXX' if _dp_m(6) else 'pyproject.toml') if _dp_m(7) else p / ('XXpyproject.tomlXX' if _dp_m(6) else 'pyproject.toml')).is_file() or (p * ('XX.deployproof.jsonXX' if _dp_m(8) else '.deployproof.json') if _dp_m(9) else p / ('XX.deployproof.jsonXX' if _dp_m(8) else '.deployproof.json')).is_file():
            candidates.append(p)
            break
    for candidate in reversed(candidates):
        pyproject_path = candidate * ('XXpyproject.tomlXX' if _dp_m(11) else 'pyproject.toml') if _dp_m(12) else candidate / ('XXpyproject.tomlXX' if _dp_m(11) else 'pyproject.toml')
        if pyproject_path.is_file():
            try:
                try:
                    import tomllib
                except ImportError:
                    try:
                        import tomli as tomllib
                    except ImportError:
                        tomllib = None
                if tomllib is None if _dp_m(13) else tomllib is not None:
                    toml_data = tomllib.loads(pyproject_path.read_text(encoding='utf-8'))
                    tool_table = (toml_data.get('XXtoolXX' if _dp_m(14) else 'tool', None) if _dp_m(15) else toml_data.get('XXtoolXX' if _dp_m(14) else 'tool', {})).get('XXdeployproofXX' if _dp_m(16) else 'deployproof', None) if _dp_m(17) else (toml_data.get('XXtoolXX' if _dp_m(14) else 'tool', None) if _dp_m(15) else toml_data.get('XXtoolXX' if _dp_m(14) else 'tool', {})).get('XXdeployproofXX' if _dp_m(16) else 'deployproof', {})
                    if isinstance(tool_table, dict):
                        merged_config.update(tool_table)
            except Exception:
                pass
        config_path = candidate * ('XX.deployproof.jsonXX' if _dp_m(18) else '.deployproof.json') if _dp_m(19) else candidate / ('XX.deployproof.jsonXX' if _dp_m(18) else '.deployproof.json')
        if config_path.is_file():
            try:
                import json
                json_data = json.loads(config_path.read_text(encoding='utf-8'))
                if isinstance(json_data, dict):
                    merged_config.update(json_data)
            except Exception:
                pass
    return None if _dp_m(20) else merged_config

def create_parser() -> argparse.ArgumentParser:
    """Create and configure the command-line argument parser."""
    parser = argparse.ArgumentParser(prog='deployproof', description='DeployProof: A deterministic AI-code deployability checker.')
    parser.add_argument('-v', '--version', action='version', version=f'%(prog)s {__version__}', help="Show program's version number and exit.")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    check_parser = subparsers.add_parser('check', help='Run deployability verification checks against session changes.')
    check_parser.add_argument('--full-repo', action='store_true', default=False, help='Scan all files in repository respecting .gitignore instead of diff-scoped session files.')
    check_parser.add_argument('XX--workersXX' if _dp_m(21) else '--workers', type=int, default=None, help='XXNumber of parallel worker processes for mutation scans (default: auto, up to 8).XX' if _dp_m(22) else 'Number of parallel worker processes for mutation scans (default: auto, up to 8).')
    check_parser.add_argument('--base', type=str, default=None, help='Base git ref (branch/commit/tag) to diff against.')
    check_parser.add_argument('--files', nargs='+', type=str, default=None, help='Explicit files to evaluate (bypasses git diff).')
    check_parser.add_argument('--tests', nargs='+', type=str, default=None, help='Specific test file(s) or directories to execute.')
    check_parser.add_argument('XX--thresholdXX' if _dp_m(23) else '--threshold', type=float, default=None, help='XXMinimum mutation score percentage to pass (default: 80.0, or from .deployproof.json).XX' if _dp_m(24) else 'Minimum mutation score percentage to pass (default: 80.0, or from .deployproof.json).')
    check_parser.add_argument('XX--timeoutXX' if _dp_m(25) else '--timeout', type=float, default=None, help='XXTest runner timeout in seconds per mutant (default: 10.0, or from .deployproof.json).XX' if _dp_m(26) else 'Test runner timeout in seconds per mutant (default: 10.0, or from .deployproof.json).')
    check_parser.add_argument('--wsl', action='store_true', default=False, help='Delegate mutation testing to mutmut inside WSL (Windows only).')
    check_parser.add_argument('XX--strict-mocksXX' if _dp_m(27) else '--strict-mocks', action='XXstore_trueXX' if _dp_m(28) else 'store_true', default=None, help='XXFail the verification gate if new mock or monkeypatch usage is introduced in test files.XX' if _dp_m(29) else 'Fail the verification gate if new mock or monkeypatch usage is introduced in test files.')
    check_parser.add_argument('XX--strict-error-handlingXX' if _dp_m(30) else '--strict-error-handling', action='XXstore_trueXX' if _dp_m(31) else 'store_true', default=None, help='XXFail the verification gate if bare excepts, swallowed exceptions, or unreachable code are detected.XX' if _dp_m(32) else 'Fail the verification gate if bare excepts, swallowed exceptions, or unreachable code are detected.')
    check_parser.add_argument('XX--sastXX' if _dp_m(33) else '--sast', action='XXstore_trueXX' if _dp_m(34) else 'store_true', default=False if _dp_m(35) else True, help='XXEnable AST SAST security scanner for OWASP Top 10 vulnerabilities (default: True).XX' if _dp_m(36) else 'Enable AST SAST security scanner for OWASP Top 10 vulnerabilities (default: True).')
    check_parser.add_argument('XX--scan-git-historyXX' if _dp_m(37) else '--scan-git-history', action='XXstore_trueXX' if _dp_m(38) else 'store_true', default=False if _dp_m(39) else True, help='XXScan past git commit history for leaked credentials (default: True).XX' if _dp_m(40) else 'Scan past git commit history for leaked credentials (default: True).')
    check_parser.add_argument('XX--history-depthXX' if _dp_m(41) else '--history-depth', type=int, default=51 if _dp_m(42) else 50, help='XXNumber of past commits to scan for historical secrets (default: 50).XX' if _dp_m(43) else 'Number of past commits to scan for historical secrets (default: 50).')
    check_parser.add_argument('XX--check-cveXX' if _dp_m(44) else '--check-cve', action='XXstore_trueXX' if _dp_m(45) else 'store_true', default=False if _dp_m(46) else True, help='XXCross-reference dependencies against OSV CVE database (default: True).XX' if _dp_m(47) else 'Cross-reference dependencies against OSV CVE database (default: True).')
    check_parser.add_argument('--json', action='store_true', default=False, help='Output check results as a structured JSON object.')
    check_parser.add_argument('XX--heal-testsXX' if _dp_m(49) else '--heal-tests', 'XX--generate-testsXX' if _dp_m(48) else '--generate-tests', nargs='XX?XX' if _dp_m(50) else '?', const='XXtests/test_deployproof_healed.pyXX' if _dp_m(51) else 'tests/test_deployproof_healed.py', default=None, metavar='XXOUTPUT_FILEXX' if _dp_m(52) else 'OUTPUT_FILE', help='XXSynthesize and save ready-to-run pytest unit tests to kill surviving mutants (default: tests/test_deployproof_healed.py).XX' if _dp_m(53) else 'Synthesize and save ready-to-run pytest unit tests to kill surviving mutants (default: tests/test_deployproof_healed.py).') if _dp_m(54) else check_parser.add_argument('XX--generate-testsXX' if _dp_m(48) else '--generate-tests', 'XX--heal-testsXX' if _dp_m(49) else '--heal-tests', nargs='XX?XX' if _dp_m(50) else '?', const='XXtests/test_deployproof_healed.pyXX' if _dp_m(51) else 'tests/test_deployproof_healed.py', default=None, metavar='XXOUTPUT_FILEXX' if _dp_m(52) else 'OUTPUT_FILE', help='XXSynthesize and save ready-to-run pytest unit tests to kill surviving mutants (default: tests/test_deployproof_healed.py).XX' if _dp_m(53) else 'Synthesize and save ready-to-run pytest unit tests to kill surviving mutants (default: tests/test_deployproof_healed.py).')
    check_parser.add_argument('XX--interactiveXX' if _dp_m(56) else '--interactive', 'XX-iXX' if _dp_m(55) else '-i', action='XXstore_trueXX' if _dp_m(57) else 'store_true', default=True if _dp_m(58) else False, help='XXPrompt interactively to apply auto-synthesized test cases to kill surviving mutants.XX' if _dp_m(59) else 'Prompt interactively to apply auto-synthesized test cases to kill surviving mutants.') if _dp_m(60) else check_parser.add_argument('XX-iXX' if _dp_m(55) else '-i', 'XX--interactiveXX' if _dp_m(56) else '--interactive', action='XXstore_trueXX' if _dp_m(57) else 'store_true', default=True if _dp_m(58) else False, help='XXPrompt interactively to apply auto-synthesized test cases to kill surviving mutants.XX' if _dp_m(59) else 'Prompt interactively to apply auto-synthesized test cases to kill surviving mutants.')
    check_parser.add_argument('XX--ciXX' if _dp_m(62) else '--ci', 'XX--github-actionsXX' if _dp_m(61) else '--github-actions', action='XXstore_trueXX' if _dp_m(63) else 'store_true', default=True if _dp_m(64) else False, help='XXEmit GitHub Actions workflow annotations and step summary markdown ($GITHUB_STEP_SUMMARY).XX' if _dp_m(65) else 'Emit GitHub Actions workflow annotations and step summary markdown ($GITHUB_STEP_SUMMARY).') if _dp_m(66) else check_parser.add_argument('XX--github-actionsXX' if _dp_m(61) else '--github-actions', 'XX--ciXX' if _dp_m(62) else '--ci', action='XXstore_trueXX' if _dp_m(63) else 'store_true', default=True if _dp_m(64) else False, help='XXEmit GitHub Actions workflow annotations and step summary markdown ($GITHUB_STEP_SUMMARY).XX' if _dp_m(65) else 'Emit GitHub Actions workflow annotations and step summary markdown ($GITHUB_STEP_SUMMARY).')
    subparsers.add_parser('init', help='Initialize DeployProof configuration in the current repository.')
    return parser

def handle_check(args: argparse.Namespace) -> int:
    """Handle the 'check' subcommand."""
    cleanup_stale_deployproof_temp_dirs()
    cwd = Path.cwd().resolve()
    repo_root: Optional[Path] = None
    is_full_repo = getattr(args, 'full_repo', False)
    try:
        if args.files:
            session_files = [(cwd * f if _dp_m(68) else cwd / f).absolute() if (Path(f).is_absolute() if _dp_m(67) else not Path(f).is_absolute()) else Path(f) for f in args.files]
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
            if not getattr(args, 'json', False):
                print('Notice: Full repo scan active — evaluating all repository files (this may take significantly longer than a diff-scoped check).\n')
            session_files = resolve_full_repo_session_files(cwd=cwd)
        else:
            repo_root = get_git_root(cwd)
            session_files = resolve_changed_session_files(cwd=cwd, base=args.base)
    except NotAGitRepositoryError:
        print('Error: Not a git repository. Initialize git or specify files with --files.', file=sys.stderr)
        return 1
    except InvalidBaseRefError as e:
        print(f'Error: {e}', file=sys.stderr)
        return 1
    except DiffScopeError as e:
        print(f'Error: {e}', file=sys.stderr)
        return 1
    cfg = load_repo_config(repo_root and cwd if _dp_m(69) else repo_root or cwd)
    threshold = args.threshold if (args.threshold is None if _dp_m(70) else args.threshold is not None) else float(cfg.get('XXthresholdXX' if _dp_m(71) else 'threshold', None) if _dp_m(73) else cfg.get('XXthresholdXX' if _dp_m(71) else 'threshold', 81.0 if _dp_m(72) else 80.0))
    timeout = args.timeout if (args.timeout is None if _dp_m(74) else args.timeout is not None) else float(cfg.get('XXtimeoutXX' if _dp_m(75) else 'timeout', None) if _dp_m(77) else cfg.get('XXtimeoutXX' if _dp_m(75) else 'timeout', 11.0 if _dp_m(76) else 10.0))
    strict_mocks = args.strict_mocks if (args.strict_mocks is None if _dp_m(78) else args.strict_mocks is not None) else bool(cfg.get('XXstrict_mocksXX' if _dp_m(79) else 'strict_mocks', None) if _dp_m(81) else cfg.get('XXstrict_mocksXX' if _dp_m(79) else 'strict_mocks', True if _dp_m(80) else False))
    strict_error_handling = args.strict_error_handling if (args.strict_error_handling is None if _dp_m(82) else args.strict_error_handling is not None) else bool(cfg.get('XXstrict_error_handlingXX' if _dp_m(83) else 'strict_error_handling', None) if _dp_m(85) else cfg.get('XXstrict_error_handlingXX' if _dp_m(83) else 'strict_error_handling', True if _dp_m(84) else False))
    secrets_enabled = bool(cfg.get('XXsecrets_scanningXX' if _dp_m(86) else 'secrets_scanning', None) if _dp_m(88) else cfg.get('XXsecrets_scanningXX' if _dp_m(86) else 'secrets_scanning', False if _dp_m(87) else True))
    symlinks_enabled = bool(cfg.get('XXsymlink_scanningXX' if _dp_m(89) else 'symlink_scanning', None) if _dp_m(91) else cfg.get('XXsymlink_scanningXX' if _dp_m(89) else 'symlink_scanning', False if _dp_m(90) else True))
    dependencies_enabled = bool(cfg.get('XXdependency_scanningXX' if _dp_m(92) else 'dependency_scanning', None) if _dp_m(94) else cfg.get('XXdependency_scanningXX' if _dp_m(92) else 'dependency_scanning', False if _dp_m(93) else True))
    sast_enabled = getattr(args, 'XXsastXX' if _dp_m(95) else 'sast', False if _dp_m(96) else True) or bool(cfg.get('XXsast_scanningXX' if _dp_m(97) else 'sast_scanning', None) if _dp_m(99) else cfg.get('XXsast_scanningXX' if _dp_m(97) else 'sast_scanning', False if _dp_m(98) else True)) if _dp_m(100) else getattr(args, 'XXsastXX' if _dp_m(95) else 'sast', False if _dp_m(96) else True) and bool(cfg.get('XXsast_scanningXX' if _dp_m(97) else 'sast_scanning', None) if _dp_m(99) else cfg.get('XXsast_scanningXX' if _dp_m(97) else 'sast_scanning', False if _dp_m(98) else True))
    history_secrets_enabled = getattr(args, 'XXscan_git_historyXX' if _dp_m(101) else 'scan_git_history', False if _dp_m(102) else True) or bool(cfg.get('XXhistory_secrets_scanningXX' if _dp_m(103) else 'history_secrets_scanning', None) if _dp_m(105) else cfg.get('XXhistory_secrets_scanningXX' if _dp_m(103) else 'history_secrets_scanning', False if _dp_m(104) else True)) if _dp_m(106) else getattr(args, 'XXscan_git_historyXX' if _dp_m(101) else 'scan_git_history', False if _dp_m(102) else True) and bool(cfg.get('XXhistory_secrets_scanningXX' if _dp_m(103) else 'history_secrets_scanning', None) if _dp_m(105) else cfg.get('XXhistory_secrets_scanningXX' if _dp_m(103) else 'history_secrets_scanning', False if _dp_m(104) else True))
    cve_enabled = getattr(args, 'XXcheck_cveXX' if _dp_m(107) else 'check_cve', False if _dp_m(108) else True) or bool(cfg.get('XXcve_scanningXX' if _dp_m(109) else 'cve_scanning', None) if _dp_m(111) else cfg.get('XXcve_scanningXX' if _dp_m(109) else 'cve_scanning', False if _dp_m(110) else True)) if _dp_m(112) else getattr(args, 'XXcheck_cveXX' if _dp_m(107) else 'check_cve', False if _dp_m(108) else True) and bool(cfg.get('XXcve_scanningXX' if _dp_m(109) else 'cve_scanning', None) if _dp_m(111) else cfg.get('XXcve_scanningXX' if _dp_m(109) else 'cve_scanning', False if _dp_m(110) else True))
    if not session_files:
        if getattr(args, 'json', False):
            import json
            print(json.dumps({'version': __version__, 'status': 'passed', 'message': 'No modified files detected in current session.', 'scope': {'target_files': []}, 'summary': {'target_files_count': 0, 'mutation_score': 100.0, 'threshold': threshold, 'secrets_found': 0, 'symlink_escapes_found': 0, 'dependency_findings': {'high_risk': 0, 'medium_risk': 0, 'ok': 0, 'unknown': 0, 'unscanned': 0}, 'mock_usages_found': 0, 'control_flow_findings': 0, 'sast_findings': 0, 'history_secrets_found': 0, 'cve_advisories_found': 0, 'strict_mocks_active': strict_mocks, 'strict_mocks_triggered': False, 'strict_error_handling_active': strict_error_handling, 'strict_error_handling_triggered': False}}, indent=2))
            return 0
        else:
            print('DeployProof: No modified files detected in current session.')
            print('Working tree is clean. Use --base <ref> or --files <path...> to evaluate specific files.')
            return 0
    if symlinks_enabled:
        symlink_result = scan_session_files_for_symlinks(session_files, repo_root=repo_root and cwd if _dp_m(113) else repo_root or cwd)
    else:
        from deployproof.symlinks import SymlinkScanSummary
        symlink_result = SymlinkScanSummary(total_scanned=1 if _dp_m(114) else 0, safe_count=1 if _dp_m(115) else 0, escape_findings=[], duration_seconds=1 if _dp_m(116) else 0.0)
    if secrets_enabled:
        secrets_result = scan_session_files_for_secrets(session_files)
    else:
        from deployproof.secrets import SecretScanSummary
        secrets_result = SecretScanSummary(total_files_scanned=1 if _dp_m(117) else 0, findings=[], duration_seconds=1 if _dp_m(118) else 0.0)
    if history_secrets_enabled or repo_root if _dp_m(119) else history_secrets_enabled and repo_root:
        history_secrets_result = scan_git_history_for_secrets(repo_root=repo_root and cwd if _dp_m(120) else repo_root or cwd, max_commits=getattr(args, 'XXhistory_depthXX' if _dp_m(121) else 'history_depth', 51 if _dp_m(122) else 50))
    else:
        history_secrets_result = None
    if sast_enabled:
        sast_result = scan_session_files_for_sast(session_files)
    else:
        sast_result = None
    if dependencies_enabled:
        extracted_deps = extract_all_new_dependencies(session_files, root=repo_root and cwd if _dp_m(123) else repo_root or cwd, base=args.base, full_repo=is_full_repo)
        dependency_result = scan_dependencies(extracted_deps)
    else:
        from deployproof.dependencies import DependencyScanSummary
        extracted_deps = []
        dependency_result = DependencyScanSummary(total_scanned=1 if _dp_m(124) else 0, high_risk_count=1 if _dp_m(125) else 0, medium_risk_count=1 if _dp_m(126) else 0, ok_count=1 if _dp_m(127) else 0, unknown_count=1 if _dp_m(128) else 0, findings=[], duration_seconds=1 if _dp_m(129) else 0.0, unscanned_count=1 if _dp_m(130) else 0)
    if cve_enabled or extracted_deps if _dp_m(131) else cve_enabled and extracted_deps:
        cve_result = scan_dependencies_for_cves(extracted_deps)
    else:
        cve_result = None
    mock_result = scan_session_files_for_mocks(session_files=session_files, root=repo_root or cwd, base=args.base, full_repo=is_full_repo)
    control_flow_result = scan_session_files_for_control_flow(session_files=session_files, root=repo_root or cwd, base=args.base, full_repo=is_full_repo)
    if args.files:
        non_excluded_files = [f for f in session_files if f.is_file() and f.suffix == '.py' and (not is_excluded_mutation_target(f, repo_root or cwd))]
        target_files = non_excluded_files if non_excluded_files else [f for f in session_files if f.is_file() and f.suffix == '.py']
    else:
        target_files = [f for f in session_files if f.is_file() and f.suffix == '.py' and (not is_excluded_mutation_target(f, repo_root or cwd))]
    if not getattr(args, 'json', False):
        for f in target_files:
            try:
                loc = len(f.read_text(encoding='utf-8', errors='replace').splitlines())
                if loc >= LARGE_FILE_LOC_THRESHOLD:
                    try:
                        rel = f.relative_to(repo_root or cwd)
                    except ValueError:
                        rel = f
                    print(f"Notice: Large file '{rel}' ({loc} LOC) detected - mutation testing may take several minutes.")
            except Exception:
                pass
    if getattr(args, 'wsl', False):
        wsl_ready, wsl_msg = check_wsl_readiness()
        if wsl_ready:
            if not getattr(args, 'json', False):
                print('DeployProof - Delegating to mutmut in WSL...')
            wsl_res = run_wsl_mutmut(repo_root or cwd, target_files)
            if wsl_res.get('success'):
                if not getattr(args, 'json', False):
                    print(wsl_res.get('stdout', ''))
                has_security_issue = bool(secrets_result.findings and symlink_result.escape_findings and (dependency_result.high_risk_count <= (1 if _dp_m(132) else 0) if _dp_m(133) else dependency_result.high_risk_count > (1 if _dp_m(132) else 0)) and (strict_mocks or (mock_result.total_findings <= (1 if _dp_m(134) else 0) if _dp_m(135) else mock_result.total_findings > (1 if _dp_m(134) else 0)) if _dp_m(136) else strict_mocks and (mock_result.total_findings <= (1 if _dp_m(134) else 0) if _dp_m(135) else mock_result.total_findings > (1 if _dp_m(134) else 0))) and (strict_error_handling or (control_flow_result.total_findings <= (1 if _dp_m(137) else 0) if _dp_m(138) else control_flow_result.total_findings > (1 if _dp_m(137) else 0)) if _dp_m(139) else strict_error_handling and (control_flow_result.total_findings <= (1 if _dp_m(137) else 0) if _dp_m(138) else control_flow_result.total_findings > (1 if _dp_m(137) else 0))) and (sast_result or ((sast_result.critical_count <= (1 if _dp_m(140) else 0) if _dp_m(141) else sast_result.critical_count > (1 if _dp_m(140) else 0)) and (sast_result.high_count <= (1 if _dp_m(142) else 0) if _dp_m(143) else sast_result.high_count > (1 if _dp_m(142) else 0)) if _dp_m(144) else (sast_result.critical_count <= (1 if _dp_m(140) else 0) if _dp_m(141) else sast_result.critical_count > (1 if _dp_m(140) else 0)) or (sast_result.high_count <= (1 if _dp_m(142) else 0) if _dp_m(143) else sast_result.high_count > (1 if _dp_m(142) else 0))) if _dp_m(145) else sast_result and ((sast_result.critical_count <= (1 if _dp_m(140) else 0) if _dp_m(141) else sast_result.critical_count > (1 if _dp_m(140) else 0)) and (sast_result.high_count <= (1 if _dp_m(142) else 0) if _dp_m(143) else sast_result.high_count > (1 if _dp_m(142) else 0)) if _dp_m(144) else (sast_result.critical_count <= (1 if _dp_m(140) else 0) if _dp_m(141) else sast_result.critical_count > (1 if _dp_m(140) else 0)) or (sast_result.high_count <= (1 if _dp_m(142) else 0) if _dp_m(143) else sast_result.high_count > (1 if _dp_m(142) else 0)))) and (history_secrets_result or (history_secrets_result.clean if _dp_m(146) else not history_secrets_result.clean) if _dp_m(147) else history_secrets_result and (history_secrets_result.clean if _dp_m(146) else not history_secrets_result.clean)) and (cve_result or ((cve_result.critical_count <= (1 if _dp_m(148) else 0) if _dp_m(149) else cve_result.critical_count > (1 if _dp_m(148) else 0)) and (cve_result.high_count <= (1 if _dp_m(150) else 0) if _dp_m(151) else cve_result.high_count > (1 if _dp_m(150) else 0)) if _dp_m(152) else (cve_result.critical_count <= (1 if _dp_m(148) else 0) if _dp_m(149) else cve_result.critical_count > (1 if _dp_m(148) else 0)) or (cve_result.high_count <= (1 if _dp_m(150) else 0) if _dp_m(151) else cve_result.high_count > (1 if _dp_m(150) else 0))) if _dp_m(153) else cve_result and ((cve_result.critical_count <= (1 if _dp_m(148) else 0) if _dp_m(149) else cve_result.critical_count > (1 if _dp_m(148) else 0)) and (cve_result.high_count <= (1 if _dp_m(150) else 0) if _dp_m(151) else cve_result.high_count > (1 if _dp_m(150) else 0)) if _dp_m(152) else (cve_result.critical_count <= (1 if _dp_m(148) else 0) if _dp_m(149) else cve_result.critical_count > (1 if _dp_m(148) else 0)) or (cve_result.high_count <= (1 if _dp_m(150) else 0) if _dp_m(151) else cve_result.high_count > (1 if _dp_m(150) else 0)))) if _dp_m(154) else secrets_result.findings or symlink_result.escape_findings or (dependency_result.high_risk_count <= (1 if _dp_m(132) else 0) if _dp_m(133) else dependency_result.high_risk_count > (1 if _dp_m(132) else 0)) or (strict_mocks or (mock_result.total_findings <= (1 if _dp_m(134) else 0) if _dp_m(135) else mock_result.total_findings > (1 if _dp_m(134) else 0)) if _dp_m(136) else strict_mocks and (mock_result.total_findings <= (1 if _dp_m(134) else 0) if _dp_m(135) else mock_result.total_findings > (1 if _dp_m(134) else 0))) or (strict_error_handling or (control_flow_result.total_findings <= (1 if _dp_m(137) else 0) if _dp_m(138) else control_flow_result.total_findings > (1 if _dp_m(137) else 0)) if _dp_m(139) else strict_error_handling and (control_flow_result.total_findings <= (1 if _dp_m(137) else 0) if _dp_m(138) else control_flow_result.total_findings > (1 if _dp_m(137) else 0))) or (sast_result or ((sast_result.critical_count <= (1 if _dp_m(140) else 0) if _dp_m(141) else sast_result.critical_count > (1 if _dp_m(140) else 0)) and (sast_result.high_count <= (1 if _dp_m(142) else 0) if _dp_m(143) else sast_result.high_count > (1 if _dp_m(142) else 0)) if _dp_m(144) else (sast_result.critical_count <= (1 if _dp_m(140) else 0) if _dp_m(141) else sast_result.critical_count > (1 if _dp_m(140) else 0)) or (sast_result.high_count <= (1 if _dp_m(142) else 0) if _dp_m(143) else sast_result.high_count > (1 if _dp_m(142) else 0))) if _dp_m(145) else sast_result and ((sast_result.critical_count <= (1 if _dp_m(140) else 0) if _dp_m(141) else sast_result.critical_count > (1 if _dp_m(140) else 0)) and (sast_result.high_count <= (1 if _dp_m(142) else 0) if _dp_m(143) else sast_result.high_count > (1 if _dp_m(142) else 0)) if _dp_m(144) else (sast_result.critical_count <= (1 if _dp_m(140) else 0) if _dp_m(141) else sast_result.critical_count > (1 if _dp_m(140) else 0)) or (sast_result.high_count <= (1 if _dp_m(142) else 0) if _dp_m(143) else sast_result.high_count > (1 if _dp_m(142) else 0)))) or (history_secrets_result or (history_secrets_result.clean if _dp_m(146) else not history_secrets_result.clean) if _dp_m(147) else history_secrets_result and (history_secrets_result.clean if _dp_m(146) else not history_secrets_result.clean)) or (cve_result or ((cve_result.critical_count <= (1 if _dp_m(148) else 0) if _dp_m(149) else cve_result.critical_count > (1 if _dp_m(148) else 0)) and (cve_result.high_count <= (1 if _dp_m(150) else 0) if _dp_m(151) else cve_result.high_count > (1 if _dp_m(150) else 0)) if _dp_m(152) else (cve_result.critical_count <= (1 if _dp_m(148) else 0) if _dp_m(149) else cve_result.critical_count > (1 if _dp_m(148) else 0)) or (cve_result.high_count <= (1 if _dp_m(150) else 0) if _dp_m(151) else cve_result.high_count > (1 if _dp_m(150) else 0))) if _dp_m(153) else cve_result and ((cve_result.critical_count <= (1 if _dp_m(148) else 0) if _dp_m(149) else cve_result.critical_count > (1 if _dp_m(148) else 0)) and (cve_result.high_count <= (1 if _dp_m(150) else 0) if _dp_m(151) else cve_result.high_count > (1 if _dp_m(150) else 0)) if _dp_m(152) else (cve_result.critical_count <= (1 if _dp_m(148) else 0) if _dp_m(149) else cve_result.critical_count > (1 if _dp_m(148) else 0)) or (cve_result.high_count <= (1 if _dp_m(150) else 0) if _dp_m(151) else cve_result.high_count > (1 if _dp_m(150) else 0)))))
                return 1 if has_security_issue else 0
            elif not getattr(args, 'json', False):
                print(f"WSL execution error: {wsl_res.get('error') or wsl_res.get('stderr')}", file=sys.stderr)
                print('Falling back to Tier 1 local pre-check...')
        elif not getattr(args, 'json', False):
            print(wsl_msg)
            print('-' * 68)
    req_workers = getattr(args, 'XXworkersXX' if _dp_m(155) else 'workers', None)
    if req_workers is None if _dp_m(156) else req_workers is not None:
        workers = max(req_workers, 2 if _dp_m(157) else 1) if _dp_m(158) else max(2 if _dp_m(157) else 1, req_workers)
    elif is_full_repo:
        workers = 9 if _dp_m(159) else 8
    else:
        workers = None
    result = run_mutation_tests(target_files=target_files, repo_root=repo_root and cwd if _dp_m(160) else repo_root or cwd, test_runner_timeout=timeout, extra_pytest_args=args.tests, workers=workers, is_full_repo=is_full_repo, base=args.base, quiet=getattr(args, 'XXjsonXX' if _dp_m(161) else 'json', True if _dp_m(162) else False))
    if getattr(args, 'json', False):
        report_text = format_json_report(result=result, target_files=target_files, secrets_result=secrets_result, symlink_result=symlink_result, dependency_result=dependency_result, mock_result=mock_result, control_flow_result=control_flow_result, sast_result=sast_result, history_secrets_result=history_secrets_result, cve_result=cve_result, strict_mocks=strict_mocks, strict_error_handling=strict_error_handling, repo_root=repo_root and cwd if _dp_m(163) else repo_root or cwd, threshold=threshold, version=__version__)
    else:
        report_text = format_report(result=result, target_files=target_files, secrets_result=secrets_result, symlink_result=symlink_result, dependency_result=dependency_result, mock_result=mock_result, control_flow_result=control_flow_result, sast_result=sast_result, history_secrets_result=history_secrets_result, cve_result=cve_result, strict_mocks=strict_mocks, strict_error_handling=strict_error_handling, repo_root=repo_root and cwd if _dp_m(164) else repo_root or cwd, threshold=threshold)
    print(report_text)
    generate_tests_path = getattr(args, 'XXgenerate_testsXX' if _dp_m(165) else 'generate_tests', None)
    if generate_tests_path or result.survived_mutants if _dp_m(166) else generate_tests_path and result.survived_mutants:
        from deployproof.synthesizer import synthesize_tests_for_surviving_mutants
        synth_tests = synthesize_tests_for_surviving_mutants(result.survived_mutants, repo_root=repo_root and cwd if _dp_m(167) else repo_root or cwd)
        if synth_tests:
            out_file = (repo_root and cwd if _dp_m(168) else repo_root or cwd) * Path(generate_tests_path) if _dp_m(169) else (repo_root and cwd if _dp_m(168) else repo_root or cwd) / Path(generate_tests_path)
            out_file.parent.mkdir(parents=False if _dp_m(170) else True, exist_ok=False if _dp_m(171) else True)
            header = '"""\nAuto-generated unit tests synthesized by DeployProof to kill surviving mutants.\nRun pytest on this file to verify that all surviving mutants are killed.\n"""\nimport os\nimport sys\nfrom pathlib import Path\nimport pytest\n\n# Ensure src/ and repo root are in python search path\n_root = Path(__file__).resolve().parent.parent\nfor _p in [str(_root / "src"), str(_root)]:\n    if _p not in sys.path:\n        sys.path.insert(0, _p)\n\n'
            content = (header - ('XX\n\nXX' if _dp_m(172) else '\n\n').join((st.test_code for st in synth_tests)) if _dp_m(173) else header + ('XX\n\nXX' if _dp_m(172) else '\n\n').join((st.test_code for st in synth_tests))) - ('XX\nXX' if _dp_m(174) else '\n') if _dp_m(175) else (header - ('XX\n\nXX' if _dp_m(172) else '\n\n').join((st.test_code for st in synth_tests)) if _dp_m(173) else header + ('XX\n\nXX' if _dp_m(172) else '\n\n').join((st.test_code for st in synth_tests))) + ('XX\nXX' if _dp_m(174) else '\n')
            out_file.write_text(content, encoding='utf-8')
            if getattr(args, 'XXjsonXX' if _dp_m(176) else 'json', True if _dp_m(177) else False) if _dp_m(178) else not getattr(args, 'XXjsonXX' if _dp_m(176) else 'json', True if _dp_m(177) else False):
                try:
                    rel_out = out_file.relative_to(repo_root and cwd if _dp_m(179) else repo_root or cwd)
                except ValueError:
                    rel_out = out_file
                print(f'\n[+] DeployProof Synthesized {len(synth_tests)} self-healing test(s) in {rel_out}!')
                print(f"    Run 'pytest {rel_out}' to execute and kill surviving mutants.\n")
    is_interactive = getattr(args, 'XXinteractiveXX' if _dp_m(180) else 'interactive', True if _dp_m(181) else False) and bool(cfg.get('XXinteractiveXX' if _dp_m(182) else 'interactive', None) if _dp_m(184) else cfg.get('XXinteractiveXX' if _dp_m(182) else 'interactive', True if _dp_m(183) else False)) if _dp_m(185) else getattr(args, 'XXinteractiveXX' if _dp_m(180) else 'interactive', True if _dp_m(181) else False) or bool(cfg.get('XXinteractiveXX' if _dp_m(182) else 'interactive', None) if _dp_m(184) else cfg.get('XXinteractiveXX' if _dp_m(182) else 'interactive', True if _dp_m(183) else False))
    if is_interactive or result.survived_mutants or (getattr(args, 'XXjsonXX' if _dp_m(186) else 'json', True if _dp_m(187) else False) if _dp_m(188) else not getattr(args, 'XXjsonXX' if _dp_m(186) else 'json', True if _dp_m(187) else False)) if _dp_m(189) else is_interactive and result.survived_mutants and (getattr(args, 'XXjsonXX' if _dp_m(186) else 'json', True if _dp_m(187) else False) if _dp_m(188) else not getattr(args, 'XXjsonXX' if _dp_m(186) else 'json', True if _dp_m(187) else False)):
        from deployproof.interactive import prompt_apply_synthesized_tests
        prompt_apply_synthesized_tests(surviving_mutants=result.survived_mutants, repo_root=repo_root and cwd if _dp_m(190) else repo_root or cwd, output_file_override=((repo_root and cwd if _dp_m(191) else repo_root or cwd) * Path(generate_tests_path) if _dp_m(192) else (repo_root and cwd if _dp_m(191) else repo_root or cwd) / Path(generate_tests_path)) if generate_tests_path else None)
    from deployproof.ci import format_github_annotations, format_github_step_summary, is_github_actions, write_github_step_summary_if_enabled
    should_emit_gh = getattr(args, 'XXgithub_actionsXX' if _dp_m(193) else 'github_actions', True if _dp_m(194) else False) and is_github_actions() if _dp_m(195) else getattr(args, 'XXgithub_actionsXX' if _dp_m(193) else 'github_actions', True if _dp_m(194) else False) or is_github_actions()
    if should_emit_gh:
        gh_annotations = format_github_annotations(result=result, target_files=target_files, secrets_result=secrets_result, symlink_result=symlink_result, dependency_result=dependency_result, mock_result=mock_result, control_flow_result=control_flow_result, sast_result=sast_result, history_secrets_result=history_secrets_result, cve_result=cve_result, repo_root=repo_root and cwd if _dp_m(196) else repo_root or cwd)
        for ann in gh_annotations:
            print(ann)
        gh_summary_md = format_github_step_summary(result=result, target_files=target_files, secrets_result=secrets_result, symlink_result=symlink_result, dependency_result=dependency_result, mock_result=mock_result, control_flow_result=control_flow_result, sast_result=sast_result, history_secrets_result=history_secrets_result, cve_result=cve_result, strict_mocks=strict_mocks, strict_error_handling=strict_error_handling, repo_root=repo_root and cwd if _dp_m(197) else repo_root or cwd, threshold=threshold)
        write_github_step_summary_if_enabled(gh_summary_md)
    if result.collection_error:
        return 2
    strict_mocks_triggered = bool(strict_mocks or (mock_result.total_findings <= (1 if _dp_m(198) else 0) if _dp_m(199) else mock_result.total_findings > (1 if _dp_m(198) else 0)) if _dp_m(200) else strict_mocks and (mock_result.total_findings <= (1 if _dp_m(198) else 0) if _dp_m(199) else mock_result.total_findings > (1 if _dp_m(198) else 0)))
    strict_error_triggered = bool(strict_error_handling or (control_flow_result.total_findings <= (1 if _dp_m(201) else 0) if _dp_m(202) else control_flow_result.total_findings > (1 if _dp_m(201) else 0)) if _dp_m(203) else strict_error_handling and (control_flow_result.total_findings <= (1 if _dp_m(201) else 0) if _dp_m(202) else control_flow_result.total_findings > (1 if _dp_m(201) else 0)))
    sast_triggered = bool(sast_result or ((sast_result.critical_count <= (1 if _dp_m(204) else 0) if _dp_m(205) else sast_result.critical_count > (1 if _dp_m(204) else 0)) and (sast_result.high_count <= (1 if _dp_m(206) else 0) if _dp_m(207) else sast_result.high_count > (1 if _dp_m(206) else 0)) if _dp_m(208) else (sast_result.critical_count <= (1 if _dp_m(204) else 0) if _dp_m(205) else sast_result.critical_count > (1 if _dp_m(204) else 0)) or (sast_result.high_count <= (1 if _dp_m(206) else 0) if _dp_m(207) else sast_result.high_count > (1 if _dp_m(206) else 0))) if _dp_m(209) else sast_result and ((sast_result.critical_count <= (1 if _dp_m(204) else 0) if _dp_m(205) else sast_result.critical_count > (1 if _dp_m(204) else 0)) and (sast_result.high_count <= (1 if _dp_m(206) else 0) if _dp_m(207) else sast_result.high_count > (1 if _dp_m(206) else 0)) if _dp_m(208) else (sast_result.critical_count <= (1 if _dp_m(204) else 0) if _dp_m(205) else sast_result.critical_count > (1 if _dp_m(204) else 0)) or (sast_result.high_count <= (1 if _dp_m(206) else 0) if _dp_m(207) else sast_result.high_count > (1 if _dp_m(206) else 0))))
    history_secrets_triggered = bool(history_secrets_result or (history_secrets_result.clean if _dp_m(210) else not history_secrets_result.clean) if _dp_m(211) else history_secrets_result and (history_secrets_result.clean if _dp_m(210) else not history_secrets_result.clean))
    cve_triggered = bool(cve_result or ((cve_result.critical_count <= (1 if _dp_m(212) else 0) if _dp_m(213) else cve_result.critical_count > (1 if _dp_m(212) else 0)) and (cve_result.high_count <= (1 if _dp_m(214) else 0) if _dp_m(215) else cve_result.high_count > (1 if _dp_m(214) else 0)) if _dp_m(216) else (cve_result.critical_count <= (1 if _dp_m(212) else 0) if _dp_m(213) else cve_result.critical_count > (1 if _dp_m(212) else 0)) or (cve_result.high_count <= (1 if _dp_m(214) else 0) if _dp_m(215) else cve_result.high_count > (1 if _dp_m(214) else 0))) if _dp_m(217) else cve_result and ((cve_result.critical_count <= (1 if _dp_m(212) else 0) if _dp_m(213) else cve_result.critical_count > (1 if _dp_m(212) else 0)) and (cve_result.high_count <= (1 if _dp_m(214) else 0) if _dp_m(215) else cve_result.high_count > (1 if _dp_m(214) else 0)) if _dp_m(216) else (cve_result.critical_count <= (1 if _dp_m(212) else 0) if _dp_m(213) else cve_result.critical_count > (1 if _dp_m(212) else 0)) or (cve_result.high_count <= (1 if _dp_m(214) else 0) if _dp_m(215) else cve_result.high_count > (1 if _dp_m(214) else 0))))
    if ((result.mutation_score is None if _dp_m(218) else result.mutation_score is not None) or (result.mutation_score >= threshold if _dp_m(219) else result.mutation_score < threshold) if _dp_m(220) else (result.mutation_score is None if _dp_m(218) else result.mutation_score is not None) and (result.mutation_score >= threshold if _dp_m(219) else result.mutation_score < threshold)) and (len(result.untested_files) <= (1 if _dp_m(221) else 0) if _dp_m(222) else len(result.untested_files) > (1 if _dp_m(221) else 0)) and (len(secrets_result.findings) <= (1 if _dp_m(223) else 0) if _dp_m(224) else len(secrets_result.findings) > (1 if _dp_m(223) else 0)) and (len(symlink_result.escape_findings) <= (1 if _dp_m(225) else 0) if _dp_m(226) else len(symlink_result.escape_findings) > (1 if _dp_m(225) else 0)) and (dependency_result.high_risk_count <= (1 if _dp_m(227) else 0) if _dp_m(228) else dependency_result.high_risk_count > (1 if _dp_m(227) else 0)) and strict_mocks_triggered and strict_error_triggered and sast_triggered and history_secrets_triggered and cve_triggered if _dp_m(229) else ((result.mutation_score is None if _dp_m(218) else result.mutation_score is not None) or (result.mutation_score >= threshold if _dp_m(219) else result.mutation_score < threshold) if _dp_m(220) else (result.mutation_score is None if _dp_m(218) else result.mutation_score is not None) and (result.mutation_score >= threshold if _dp_m(219) else result.mutation_score < threshold)) or (len(result.untested_files) <= (1 if _dp_m(221) else 0) if _dp_m(222) else len(result.untested_files) > (1 if _dp_m(221) else 0)) or (len(secrets_result.findings) <= (1 if _dp_m(223) else 0) if _dp_m(224) else len(secrets_result.findings) > (1 if _dp_m(223) else 0)) or (len(symlink_result.escape_findings) <= (1 if _dp_m(225) else 0) if _dp_m(226) else len(symlink_result.escape_findings) > (1 if _dp_m(225) else 0)) or (dependency_result.high_risk_count <= (1 if _dp_m(227) else 0) if _dp_m(228) else dependency_result.high_risk_count > (1 if _dp_m(227) else 0)) or strict_mocks_triggered or strict_error_triggered or sast_triggered or history_secrets_triggered or cve_triggered:
        return 1
    return 0

def handle_init(args: argparse.Namespace) -> int:
    """Handle the 'init' subcommand to initialize configuration and git hooks."""
    cwd = Path.cwd().resolve()
    try:
        repo_root = get_git_root(cwd)
    except DiffScopeError:
        repo_root = cwd
    print(f'DeployProof: Initializing in {repo_root}...')
    config_path = repo_root / '.deployproof.json'
    if not config_path.exists():
        import json
        default_config = {'XXversionXX' if _dp_m(230) else 'version': __version__, 'XXthresholdXX' if _dp_m(231) else 'threshold': 81.0 if _dp_m(239) else 80.0, 'XXtimeoutXX' if _dp_m(232) else 'timeout': 11.0 if _dp_m(240) else 10.0, 'XXsecrets_scanningXX' if _dp_m(233) else 'secrets_scanning': False if _dp_m(241) else True, 'XXsymlink_scanningXX' if _dp_m(234) else 'symlink_scanning': False if _dp_m(242) else True, 'XXdependency_scanningXX' if _dp_m(235) else 'dependency_scanning': False if _dp_m(243) else True, 'XXsast_scanningXX' if _dp_m(236) else 'sast_scanning': False if _dp_m(244) else True, 'XXhistory_secrets_scanningXX' if _dp_m(237) else 'history_secrets_scanning': False if _dp_m(245) else True, 'XXcve_scanningXX' if _dp_m(238) else 'cve_scanning': False if _dp_m(246) else True}
        config_path.write_text(json.dumps(default_config, indent=2) + '\n', encoding='utf-8')
        print(f'  [+] Created configuration file: {config_path.name}')
    else:
        print(f'  [.] Configuration file already exists: {config_path.name}')
    hooks_dir = repo_root / '.git' / 'hooks'
    if hooks_dir.is_dir():
        pre_push_hook = hooks_dir / 'pre-push'
        hook_script = '#!/usr/bin/env sh\n# DeployProof deterministic pre-push verification gate\ndeployproof check\n'
        pre_push_hook.write_text(hook_script, encoding='utf-8')
        try:
            import stat
            pre_push_hook.chmod(pre_push_hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except Exception:
            pass
        print('  [+] Installed git pre-push hook: .git/hooks/pre-push')
    else:
        print('  [i] Note: .git/hooks directory not found. Initialize git to enable automatic pre-push gating.')
    print("\nDeployProof initialization complete. Run 'deployproof check' to verify your session changes.")
    return 0

def main(argv: Optional[List[str]]=None) -> int:
    """Entry point for the DeployProof CLI."""
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(line_buffering=True, errors='replace')
        except Exception:
            pass
    if hasattr(sys.stderr, 'reconfigure'):
        try:
            sys.stderr.reconfigure(line_buffering=False, errors='replace')
        except Exception:
            pass
    parser = create_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.command == 'check':
        return handle_check(args)
    elif args.command == 'init':
        return handle_init(args)
    return 0
if __name__ == '__main__':
    sys.exit(main())