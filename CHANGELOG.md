# Changelog

All notable changes to DeployProof will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
