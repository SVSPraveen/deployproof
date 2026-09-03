# Changelog

All notable changes to DeployProof will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.19] - 2026-09-03

### Changed
- **Top Hero Walkthrough Banner**: Replaced static header mockup with the dynamic, high-fidelity animated terminal walkthrough GIF (`assets/demo.gif`) as the primary hero asset on GitHub and PyPI.

## [1.1.18] - 2026-09-03

### Added
- **Animated Terminal Walkthrough GIF**: Added high-fidelity virtual terminal recording (`assets/demo.gif`) showcasing diff-scoped pre-push mutation verification, surviving mutant detection, self-healing test synthesis, and clean JSON streaming across `README.md`, PyPI, and the documentation portal.

### Changed
- **Documentation Restructuring**: Re-aligned `README.md` and product docs to clearly highlight in-memory AST mutation testing as the core engine, positioning SAST, secrets scanning, dependency verification, and symlink defenses as comprehensive companion security gates.
- **Enhanced PyPI & Search Engine SEO**: Optimized package metadata, titles, keywords, and description for Google indexing and PyPI search visibility.
- **Removed Fabricated Timing Estimates**: Replaced estimated timing multipliers with honest relative mechanism comparisons (in-memory AST schemata vs disk rewrites).

## [1.1.17] - 2026-09-03

### Added
- **Comprehensive WSL Test Suite**: Added 100% branch and edge-case unit tests for `wsl.py`, boosting `wsl.py` mutation score to 96.8% and expanding total test count to **278 tests** (100% passing).
- **Embedded Architecture Hero Asset**: Added visual hero diagram to the top of `README.md`.
- **Restored Reverse Dependency Investigation**: Restored `INVESTIGATION_blastradius.md` to repository tracking, linking with `FUTURE_SCOPE.md`.

### Fixed
- **WSL Path Quoting with Spaces**: Wrapped all interpolated WSL paths in `shlex.quote()` to prevent bash word-splitting on standard Windows user profiles with spaces (e.g. `C:\Users\John Doe\Projects`).
- **Fail-Closed Verification Gates**: Enforced strict fail-closed behavior on invalid inputs:
  - Non-existent files passed to `--files` or `--tests` immediately exit with code `1` and descriptive stderr diagnostics.
  - Python files with `SyntaxError` are flagged with CRITICAL severity (`DP-SAST-000`) and halt mutation checks as unparsable collection errors (exit code `2`/`1`).
- **Transparent Privacy & Network Documentation**: Accurately documented read-only queries to both the official PyPI registry (package existence verification) and the OSV database (CVE advisories) across `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, and the product portal.
- **Linter & Typing Cleanups**: Cleaned up unused variables and unused imports across `reporter.py`, `secrets.py`, `synthesizer.py`, `wsl.py`, `mutator.py`, and `diff.py`. Tightened `zip()` calls in `synthesizer.py` with `strict=True`.

## [1.1.16] - 2026-09-03

### Added
- **Automatic Persistent Audit Logs (`.deployproof/report.txt`)**: Every run (both diff-scoped `deployproof check` and `deployproof check --full-repo`) automatically records the complete, untruncated 7-gate verification report into `.deployproof/report.txt` (or `.deployproof/report.json` if using `--json`).
- **Custom Report Output (`-o` / `--output <path>`)**: Allows directing the full verification report to any custom destination file path.
- **Inline Test Suggestion Control (`--suggest-tests`)**: Gated inline test code generation behind `--suggest-tests` and `--heal-tests`, ensuring terminal outputs remain concise and readable while preserving full synthesized test suite export capabilities.

### Fixed
- **Terminal Buffer Overflow**: Fixed massive terminal dumps during multi-thousand mutant full-repo audits by removing unsolicited test synthesis code from default console reports.

## [1.1.15] - 2026-09-03

### Fixed
- **Clean Source Restoration (`cli.py`)**: Completely restored `src/deployproof/cli.py` to clean hand-written source, purging all accidental in-memory mutation schemata artifacts (`_dp_m(...)`, `XX...XX` literals, and ternary switches) committed prior to v1.1.14.
- **Unscanned Dependency JSON Crash**: Fixed `NameError: name 'rel_src' is not defined` when reporting unscanned dependencies in `format_json_report()`, aligning JSON reports with plain-text formatting.
- **Accurate Mutated Line Reconstruction**: Propagated AST node column offsets (`col_offset`, `end_col_offset`) across binary operators, comparisons, unary expressions, calls, and boolean operations. Added statement-level return mutation reconstruction (`return <expr>` &rarr; `return None`) and exact token substitution so surviving mutant diffs accurately reflect code changes.
- **Multi-Mutant Test Synthesis on Shared Lines**: Updated `synthesizer.py` to assign unique test names and prevent dropping subsequent mutants occurring on the same source line. Updated `reporter.py` with dual-map lookup (`mutant_id` + line fallback) so all surviving mutants render suggested pytest tests.
- **Python 3.12+ f-String Schemata Compilation**: Added `visit_JoinedStr` to `MutationSchemataTransformer` to safely bypass placing `IfExp` nodes inside raw `JoinedStr.values` constant fragments, allowing all 18 repository modules to compile 6,374 schemata mutants without `ValueError` exceptions.

## [1.1.14] - 2026-09-02

### Added
- **`pyproject.toml` Configuration Engine (`[tool.deployproof]`)**: Native support for PEP 518 `pyproject.toml` configuration table, standardizing threshold, worker count, timeout, and verification gate toggles alongside `[tool.pytest]` and `[tool.ruff]`.
- **Interactive Quick-Fix Mode (`-i` / `--interactive`)**: Terminal interactive prompt allowing developers to inspect and append auto-synthesized test cases with single-keystroke confirmation, featuring TTY detection for zero-blocking CI execution.
- **In-Memory Schemata Mutation Engine**: Injects all AST mutants into a unified compiled tree switched dynamically in warm Python interpreter memory (`__DEPLOYPROOF_MUTANT__`), completely bypassing disk I/O and process spawn overhead.
- **Dead-Code & Algebraic Equivalence Pruning**: Static taint and dead-code reachability analyzer pruning equivalent mutants and unreachable branches before test dispatch.
- **Actionable Test Synthesis Engine ("Self-Healing Tests")**: `--generate-tests` / `--heal-tests` automatically synthesizes ready-to-run pytest test cases with argument type inference, class method instantiation, async/await definitions, and boundary value inversion.
- **GitHub Actions Native CI Integration**: Inline PR annotations (`::error` / `::warning`) on modified code lines and rich Markdown verification dashboards written directly to `$GITHUB_STEP_SUMMARY`.
- **Standard `pre-commit` Framework Hook**: Added `.pre-commit-hooks.yaml` exposing `deployproof`, `deployproof-check`, and `deployproof-full` hooks for the global `pre-commit` framework.
- **Modern Documentation & Product Portal**: Created full-featured documentation website in `/docs` ready for GitHub Pages hosting with interactive terminal playgrounds, Ctrl+K live search, and 7-gate architectural specifications.

## [1.1.2] - 2026-09-02

### Added
- **`pyproject.toml` Configuration Engine (`[tool.deployproof]`)**: Native support for PEP 518 `pyproject.toml` configuration table, standardizing threshold, worker count, timeout, and verification gate toggles alongside `[tool.pytest]` and `[tool.ruff]`.
- **Interactive Quick-Fix Mode (`-i` / `--interactive`)**: Terminal interactive prompt allowing developers to inspect and append auto-synthesized test cases with single-keystroke confirmation, featuring TTY detection for zero-blocking CI execution.
- **In-Memory Schemata Mutation Engine**: Injects all AST mutants into a unified compiled tree switched dynamically in warm Python interpreter memory (`__DEPLOYPROOF_MUTANT__`), completely bypassing disk I/O and process spawn overhead.
- **Dead-Code & Algebraic Equivalence Pruning**: Static taint and dead-code reachability analyzer pruning equivalent mutants and unreachable branches before test dispatch.
- **Actionable Test Synthesis Engine ("Self-Healing Tests")**: `--generate-tests` / `--heal-tests` automatically synthesizes ready-to-run pytest test cases with argument type inference, class method instantiation, async/await definitions, and boundary value inversion.
- **GitHub Actions Native CI Integration**: Inline PR annotations (`::error` / `::warning`) on modified code lines and rich Markdown verification dashboards written directly to `$GITHUB_STEP_SUMMARY`.
- **Standard `pre-commit` Framework Hook**: Added `.pre-commit-hooks.yaml` exposing `deployproof`, `deployproof-check`, and `deployproof-full` hooks for the global `pre-commit` framework.
- **Modern Documentation & Product Portal**: Created full-featured documentation website in `/docs` ready for GitHub Pages hosting with interactive terminal playgrounds, Ctrl+K live search, and 7-gate architectural specifications.

## [1.1.11] - 2026-09-01

### Changed
- **PyPI Clean Rendering**: Removed relative image tag from `README.md` to prevent broken image box on PyPI release page.
- **Universal Codebase Positioning**: Elevated package positioning and metadata to support modern Python codebases generally (built for human engineering teams and AI-assisted workflows alike).
- **Expanded PyPI Metadata**: Added `code-quality`, `developer-tools`, and `python-testing` keywords to `pyproject.toml`.
- **Recommended Installation**: Promoted `pipx install deployproof` as the primary installation method for isolated global CLI access.

### Documentation
- **Estimated Timings Disclaimer**: Added explicit disclaimer in `README.md` and architectural specifications noting that execution durations are empirical estimates and vary based on test suite speed, hardware clock/RAM, and codebase size.
- **Authentic Terminal Visuals**: Updated documentation assets with authentic Windows Terminal / PowerShell 7 screenshots demonstrating real execution, four core workflow commands, and actionable findings reports.

## [1.1.0] - 2026-09-01

### Added
- **Hardware & Memory Sizing Architecture**: Added comprehensive RAM requirements, sizing formulas, and an explicit **Diff Scoped vs Full Repo Memory Comparison** table documenting process RSS, page cache footprints, and multicore scaling guidance for 8 GB, 16 GB, and 32 GB+ workstations.

### Fixed
- **Clean CI Baseline Runner Fallback**: Proactively inspect module availability with `importlib.util.find_spec("coverage")` before invoking coverage runners. If `coverage` is absent (such as in minimal CI/CD test matrices) or fails at startup, DeployProof directly and cleanly falls back to standard `pytest`, preventing false `no_tests_ran` collection outcomes.
- **Dynamic Version Tests**: Updated CLI test suite to assert dynamically against package `__version__`.
- **Synthetic Secret Test Fixtures**: Refactored dummy secret fixtures in CLI tests to avoid static pattern collisions with pre-push credential scanners.

## [1.0.1] - 2026-09-01

### Fixed
- **Clean CI Baseline Runner Fallback**: Proactively inspect module availability with `importlib.util.find_spec("coverage")` before invoking coverage runners. If `coverage` is absent (such as in minimal CI/CD test matrices) or fails at startup, DeployProof directly and cleanly falls back to standard `pytest`, preventing false `no_tests_ran` collection outcomes.
- **Optional Dev Dependencies**: Added `coverage>=7.0.0` to `[project.optional-dependencies] dev` in `pyproject.toml` so automated test suites exercise coverage-guided test selection during CI runs.

### Added
- **Hardware & Memory Sizing Architecture**: Added comprehensive RAM requirements, sizing formulas, and an explicit **Diff Scoped vs Full Repo Memory Comparison** table documenting process RSS, page cache footprints, and multicore scaling guidance for 8 GB, 16 GB, and 32 GB+ workstations.

## [1.0.0] - 2026-09-01

### Added
- **Import-Graph-Based Test Discovery Rewrite**: Replaced filename-stem-only test matching with AST static import graph parsing combined with tiered precision discovery (Tier 1 direct stem and submodule imports, Tier 2 parent package fallback). Accurately discovers non-homonymous test suites across third-party repos (confirmed via `click`: 18.7% -> 79.3%) and self-audit (`deployproof_self`: 76.3%, correctly flagged FAILED with unlinked stress fixtures properly marked UNTESTED rather than falsely SURVIVED).
- **Full Repository Audit Mode (`--full-repo`)**: Added `--full-repo` flag to `deployproof check` to evaluate all tracked non-ignored files across the repository root instead of diff-scoped changes.
- **Isolated Multi-Worker Parallel Engine**: Added `ProcessPoolExecutor`-based parallelization for `--full-repo` mode with `--workers` flag. Each worker executes in an isolated PID-keyed filesystem sandbox (`worker_{pid}`) with independent pytest cache (`cache_dir`) and temp directories (`--basetemp`), eliminating cross-worker file lock and mutation race conditions.
- **Live Periodic Progress Reporting**: Live progress output (`[X/Y mutants | A/B files] elapsed: MmSSs`) with unbuffered line-level output (`sys.stdout.reconfigure(line_buffering=True)` and explicit `flush=True`) during long-running mutation runs, ensuring live terminal and redirected log updates (confirmed via `colorama` demo run).

### Fixed
- **Sandbox Snapshot Cleanup Race Condition**: Resolved an issue where cross-run temp directory cleanup misidentified active sibling processes as dead on Windows due to `os.kill(pid, 0)` failure (`WinError 87`), wiping active worker sandboxes mid-run. Replaced with Windows Win32 API (`kernel32.OpenProcess`/`GetExitCodeProcess`) and implemented a self-healing fallback in `_run_single_mutant_in_sandbox` that automatically restores missing files directly from the clean snapshot directory.
- **Adaptive Baseline Timeout Scaling for `--full-repo`**: Fixed baseline collection timeout calculation to dynamically scale with the number of test files, payload size (in KB), and multi-file coverage overhead ($\max(60.0, \text{files} \times 35.0, \text{KB} \times 2.5) \times 1.25$), preventing timeout crashes when collecting coverage maps across large combined test suites (e.g. `requests` 9 test suites scaling from 135s -> 518s).
- **Legacy Python 2 Standard Library Compatibility Shims**: Added `LEGACY_STDLIB_MODULES` (`StringIO`, `cStringIO`, `BaseHTTPServer`, `SimpleHTTPServer`, `urllib2`, `urlparse`, `httplib`, `Cookie`, `cookielib`, `Queue`, `SocketServer`, `ConfigParser`, etc.) to standard library exclusions in dependency scanning, eliminating false-positive slopsquatting/hallucination warnings in Python 2/3 compatibility shims (confirmed via `compat.py`: 2 false positives -> 0).
- **CI/CD Script Scoping Exclusion**: Added `.github` to `IGNORED_DIRS` and `is_excluded_mutation_target`, preventing GitHub Actions internal release/helper scripts from polluting mutation pools and causing false 0% scores on libraries like `pydantic`.
- **Traceback-Anchored Mutant Kill Classification**: Runner-error mutants (`exit code 1`) are reclassified as `KILLED` only if the error traceback explicitly anchors to the mutated source file and line. Generic or unanchored environment errors remain as `RUNNER_ERROR` and are displayed separately.
- **Score Fraction Formatting**: Corrected mutation score fraction display in reporter to truthfully reflect valid mutants killed versus excluded runner errors (e.g. `(4/4 valid mutants killed, 1 error excluded)`).

## [0.2.2] - 2026-08-30

### Fixed
- **CLI Large File Notice Threshold**: Corrected the file-size threshold condition in `cli.py` to `loc >= LARGE_FILE_LOC_THRESHOLD`, eliminating false "large file" warnings on small files.
- **Windows Cleanup Race Protection**: Hardened temporary directory cleanup in subprocess-heavy tests with `ignore_cleanup_errors=True` and child termination delay to prevent transient file locking errors on Windows.

## [0.2.1] - 2026-08-30

### Fixed
- **Targeted Bytecode Cache Invalidation**: `_restore_current_mutant_file()` now uses `importlib.util.cache_from_source()` to remove the exact `.pyc` bytecode cache for restored files, preventing stale bytecode execution across mutant runs.
- **Baseline Test Timeout Scaling**: Dynamic scaling for multi-file subprocess test suites to prevent false collection timeouts on heavy process-level test fixtures.

## [0.2.0] - 2026-08-30

### Fixed
- **Recursive & Multi-Directory Test Discovery**: Resolved an issue where `discover_target_tests` returned 0 discovered tests on repositories with nested or singular test directories (`test/` vs `tests/`, e.g., `urllib3`, `attrs`, `pydantic`, `marshmallow`), eliminating false 0.0% scores.
- **Secrets Scanner Precision**: Eliminated false positives on identifiers such as `pass_arg`, `pass_script_info`, `pass_original`, schema field declarations (`password = fields.Str(...)`), and `ContextVar` tokens (`self.token = ...`) by replacing broad substring matching with targeted credential-variable regex pattern boundaries, mandatory quoted-string literal validation in code files, and Shannon entropy scoring (threshold >= 3.8) on assigned values.
- **Dependency & Manifest Scanner False Positives**:
  - Enforced strict requirements manifest path matching to prevent non-manifest text files (such as `LICENSE.txt`) from triggering phantom PyPI queries.
  - Added canonical translation mapping for import names that differ from PyPI distribution names (e.g., `OpenSSL` -> `pyOpenSSL`, `yaml` -> `PyYAML`, `bs4` -> `beautifulsoup4`, `PIL` -> `Pillow`).
  - Added recognition for Python 3.10-3.14+ stdlib modules (`annotationlib`, `_typeshed`) and namespace umbrella roots.
- **Mutant Snippet Column Alignment**: Fixed visual snippet reconstruction to use AST `col_offset` and token slicing instead of naive string `.replace()`, preventing corruption when replaced literals matched substrings in preceding variable names (e.g. `is_py3 = ...`).
- **Internal Swallowed Exceptions**: Fixed 4 confirmed swallowed-exception findings in DeployProof's own codebase (`symlinks.py` x2, `dependencies.py`, `mutator.py`), detected by DeployProof running against itself.

### Added
- **Baseline Collection Failure Isolation**: Distinctly detects when a test suite fails before mutation testing begins (pytest exit codes 2/3/4, `ModuleNotFoundError`, `ImportError`, conftest crashes). Returns exit code `2` with actionable diagnostic error output instead of a misleading `0.0%` mutation score.
- **Signal-Safe Disk Restoration**: Installed signal handlers for `SIGINT`, `SIGTERM`, and `SIGBREAK` (Windows console break), backed by `atexit`, guaranteeing that mutated source files are restored to their original unmutated contents even if the process is interrupted mid-run.
- **Expanded Test Suite**: Unit test suite expanded from 79 to 94 tests, with 11/11 launch-day stress test fixtures passing.
