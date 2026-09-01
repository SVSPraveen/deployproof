# Changelog

All notable changes to DeployProof will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
