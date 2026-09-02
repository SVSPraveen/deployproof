# DeployProof Architectural Decisions (DECISIONS.md)

*Document updated: August 30, 2026*  
*Scope: V1 Diff-Scoping Strategy, Two-Tier Mutation Architecture, Production Hardening & v0.2.2 Safety Guarantees*

---

## 1. Diff-Scoping Strategy Decision

### The Problem
AI-assisted development happens in rapid iterations. A developer may run `deployproof check` at different points in their workflow:
- **Mid-session**: The AI IDE just edited 2 files in the working directory; nothing has been staged or committed yet.
- **Post-commit**: The developer committed the changes locally and wants to run a final check before pushing.
- **CI / Pull Request**: A CI pipeline wants to test all commits introduced in a feature branch against the base branch (`main`).

Mutation testing is computationally expensive if run across an entire repository. DeployProof must scope execution strictly to the files changed in the active session without crashing on edge cases (fresh repos, single-commit repos, uncommitted edits, or non-git folders).

---

### Comparison of Evaluated Options

| Option | How it Works | Strengths | Failure Modes & Weaknesses |
|---|---|---|---|
| **1. Diff against default branch (`main`/`master`)** | `git diff main...HEAD` | Captures full branch delta for PRs. | Fails if `main` branch does not exist locally; fails on fresh repos before first push; ignores uncommitted working-tree edits; too broad for long-lived branches. |
| **2. Diff against `HEAD~1` (last commit only)** | `git diff HEAD~1` | Fast; captures the immediate last commit. | Crashes with fatal git error on fresh repositories with only 1 commit; completely ignores unstaged/staged working-tree changes mid-session. |
| **3. `--base <ref>` flag** | `git diff <ref>...HEAD` | Precise and essential for CI / PR pipelines. | As a mandatory requirement, introduces CLI friction for local developers who just want to run `deployproof check`. |
| **4. Diff against working tree (uncommitted changes)** | `git diff HEAD` + untracked | Directly matches mid-session edits before committing. | If the developer commits their files *before* running `deployproof check`, working-tree diff produces 0 files. |

---

### The Chosen Strategy: Smart Session Cascade with `--base` Override

To deliver a zero-friction experience for developers while supporting CI workflows, DeployProof adopts a **3-Tier Smart Session Cascade**:

```
                              deployproof check
                                      │
                         Is --base <ref> provided?
                                ├── YES ──► Diff <base> against working tree / HEAD
                                │
                                └── NO (Default Cascade)
                                      │
                     Step 1: Check Working Tree
                     (Unstaged + Staged + Untracked .py files)
                                      │
                           Are changed .py files found?
                                ├── YES ──► Scope mutation testing to these files
                                │
                                └── NO (Working tree is clean)
                                      │
                     Step 2: Check Latest Commit (HEAD)
                     (git diff-tree --root or HEAD~1 if history exists)
                                      │
                           Are changed .py files found?
                                ├── YES ──► Scope mutation testing to these files
                                │
                                └── NO
                                      │
                     Step 3: Safe Graceful Messaging
                     (Inform user working tree is clean, exit 0, no crash)
```

#### Safe Failure & Edge-Case Handling:
1. **Not a Git Repository**: If executed outside a git repo, DeployProof prints:
   `Error: Not a git repository. Initialize git or specify files with --files.`
   (Clean exit, zero Python tracebacks).
2. **Fresh Repository (0 commits)**: Untracked and staged `.py` files in the working tree are discovered via `git status --porcelain`. If no files are modified, it reports:
   `No modified Python files detected in current session.`
3. **Single-Commit Repository (1 commit, clean tree)**: When checking `HEAD`, DeployProof safely inspects root commit files using `git diff-tree --root` without invoking `HEAD~1` (which would error in git).
4. **Invalid `--base <ref>`**: If an invalid base ref is given (e.g. `--base non-existent`), DeployProof prints:
   `Error: Git reference 'non-existent' does not exist.`

---

## 2. Two-Tier Mutation System Architecture

### Tier 1: Local Pre-Check (Approximate AST Mutator)
- **Role**: Fast pre-commit sanity check running locally across all OS environments (Windows, macOS, Linux).
- **Labeling**: Every terminal report is explicitly labeled:  
  `LOCAL PRE-CHECK (approximate) — not the verified score`
- **Known Limitations**:
  - This is a lightweight AST mutator implemented in DeployProof.
  - Its operator coverage is currently limited to basic `Compare`, `BinOp`, `BoolOp`, `AugAssign`, and `Constant` mutations.
  - It does NOT mutate advanced language semantics (e.g. ternary branches inside f-strings, walrus expressions, async/await coroutine lifecycle, pattern match structures, yield statements).
  - Line-number snippet reconstruction can drift when `ast.unparse()` re-formats multi-line constructs.

### Tier 2: Verified Authoritative Score (`mutmut` in CI)
- **Role**: The official, authoritative mutation score referenced publicly for the repository.
- **Environment**: Executes in GitHub Actions on `ubuntu-latest` where `mutmut` runs natively with full POSIX process isolation and coverage tracking.
- **Workflow**: Triggered automatically on push/PR, scoped to the session diff.

---

## 3. Tier 1 AST Mutator Edge-Case Validation Findings

We tested the Tier 1 AST mutator against 7 advanced Python language constructs to document exact capabilities, omissions, and failure modes:

| Construct Tested | Fixture Pattern | Mutants Generated | Handled Correctly | Silently Skipped (Omissions) | Crashes |
|---|---|---|---|---|---|
| **Decorators** | `@lru_cache(maxsize=128)`<br>`@dec(threshold=50, is_enabled=False)` | 7 | Mutated function body arithmetic/constants and literal arguments inside decorator calls (`maxsize=129`, `threshold=51`, `is_enabled=True`). | Does not mutate decorator presence (e.g. stripping or replacing decorators). Line snippet alignment drifted on unparse. | 0 |
| **F-strings** | `f"User: {name}, Status: {'Admin' if is_active else 'Guest'}, High: {score > 100}, Next: {score + 1}"` | 4 | Mutated binary operators and comparisons inside embedded `{}` expressions (`score <= 100`, `score - 1`). | **Silently skipped** ternary conditions (`'Admin' if is_active else 'Guest'`) and string literal interpolations. | 0 |
| **Walrus Operator** | `if (n := len(items)) > 10:` | 5 | Mutated outer comparison (`> 10` → `<= 10`) and downstream arithmetic. | **Silently skipped** walrus assignment expression target and binding semantics. | 0 |
| **Async / Await** | `async def fetch(): await client.get()` | 5 | Mutated inner comparison (`<= 0`), boolean flags, and `is None` checks. | **Silently skipped** `await` keyword operations (e.g. dropping `await` or altering coroutine resolution). | 0 |
| **Comprehensions** | `[x * 2 for x in items if x > 0 and x % 2 == 0]`<br>`{k: v for k, v in d.items() if v != None}` | 15 | Mutated comprehension body expressions, modulo arithmetic, comparison filters, and boolean `and`/`or` chains. | **Silently skipped** comprehension structure (e.g. mutating list comp to empty generator or swapping key/value in dict comp). | 0 |
| **Match Statements** | `case {"action": "delete", "id": uid} if uid > 0:`<br>`case [x, y] if x == y:` | 3 | Mutated match case guard expressions (`if uid <= 0`, `if x != y`). | **Silently skipped** structural pattern shapes (mapping patterns, sequence patterns, literal values in patterns). | 0 |
| **Generators / Yield** | `while count < limit:`<br>`  yield count * 10` | 10 | Mutated while-loop comparisons, modulo checks, yielded expression arithmetic, and augmented assignments (`+=` → `-=`). | **Silently skipped** `yield` statement semantics (e.g. mutating `yield` to `return` or removing `yield`). | 0 |

### Summary of Edge-Case Analysis:
1. **Zero Hard Crashes**: `ast.parse` and `ast.unparse` successfully parsed and regenerated valid Python ASTs across all 7 Python 3.10+ constructs without throwing unhandled exceptions.
2. **Silent Skipping of Construct-Specific Semantics**: The mutator only mutates nested `Compare`, `BinOp`, `BoolOp`, and `Constant` nodes that happen to be children of these constructs. It **silently omits** structural mutations specific to walrus bindings, f-string ternaries, match pattern schemas, await removal, and generator yields.
3. **Validation Conclusion**: Tier 1 is suitable strictly as a fast local pre-check for basic logic errors; Tier 2 (`mutmut` in CI) remains mandatory for verified mutation scoring.

---

## 4. Real-World Multi-Repository Validation & Production Hardening

*Evaluation Date: August 29–30, 2026*  
*Target Repositories*: 10 prominent open-source Python codebases (`requests`, `flask`, `httpx`, `click`, `jinja`, `marshmallow`, `urllib3`, `attrs`, `pydantic`, `rich`).

Testing DeployProof against diverse, large-scale production codebases revealed 5 critical real-world edge cases that led to architectural hardening across the mutator, secrets scanner, dependency scanner, and CLI reporting layers:

### 1. Recursive & Multi-Pattern Test Discovery (`mutator.py`)
- **Observed Defect**: The initial test discovery looked exclusively for `tests/test_<stem>.py` at the repo root. Real repos use diverse structures:
  - Singular `test/` directory (`urllib3`).
  - Nested test subdirectories mirroring package structure (e.g. `tests/models/test_models.py` for `httpx/_models.py`).
  - Leading underscore convention in source files (`src/attr/_make.py` tested by `tests/test_make.py`).
- **Architectural Decision**: Implemented recursive test discovery searching both `tests/` and `test/` trees at arbitrary depth, matching `test_<stem>.py`, `<stem>_test.py`, and normalized stems with leading underscores stripped.

### 2. Value-Based & Entropy-Driven Credential Detection (`secrets.py`)
- **Observed Defect**: Name-based substring heuristics (`"token"`, `"pass_"`) produced unacceptable false-positive rates on production code:
  - Keyword argument names: `pass_arg`, `pass_script_info`, `pass_original` (in `click`, `flask`).
  - Schema/documentation field declarations: `password = fields.Str(...)` (in `marshmallow`).
  - Context tokens: `self.token = _CURRENT_CONTEXT.set(...)` (in `httpx`).
- **Architectural Decision**: Replaced broad identifier substring matching with multi-stage validation:
  - Targeted credential-variable regex pattern boundaries (`CREDENTIAL_VAR_RE`) to avoid matching non-credential identifiers like `pass_arg`.
  - Mandatory quoted-string literal validation in code files (`is_non_secret_code_or_schema`), immediately filtering out unquoted code expressions (such as schema definitions like `fields.Str(...)` or context tokens like `_CURRENT_CONTEXT.set(...)`).
  - Shannon entropy threshold scoring (`entropy >= 3.8`) on candidate string literal values to separate random keys from regular text.
  - Explicit pattern matching for recognized credential formats (OpenAI `sk-`, Anthropic `sk-ant-`, AWS `AKIA`, GitHub `ghp_`, Stripe `sk_live_`, RSA/SSH private keys).

### 3. Manifest Filtering & Import-to-Distribution Mapping (`dependencies.py`)
- **Observed Defect**:
  - Any `.txt` file was previously treated as a requirements manifest, causing legal text in `LICENSE.txt` (e.g. "THIS", "PROFITS", "NEGLIGENCE", "1.", "2.") to trigger phantom PyPI queries.
  - Top-level Python import names were queried directly against PyPI distribution names, causing false `HIGH_RISK` (404) flags on valid packages where import and distribution names differ (e.g., `import OpenSSL` vs. PyPI `pyOpenSSL`).
- **Architectural Decision**:
  - Enforced strict requirements manifest path matching (`requirements*.txt`, `*-requirements.txt`, `requirements/*.txt`, `constraints*.txt`, `pyproject.toml`, `setup.cfg`, `setup.py`).
  - Built-in canonical translation map for known import-to-distribution mismatches (`OpenSSL` → `pyOpenSSL`, `yaml` → `PyYAML`, `bs4` → `beautifulsoup4`, `PIL` → `Pillow`, `dateutil` → `python-dateutil`, `sklearn` → `scikit-learn`, `cv2` → `opencv-python`, `jwt` → `PyJWT`, `dotenv` → `python-dotenv`, `google.protobuf` → `protobuf`).

### 4. AST Column-Offset Snippet Reconstruction (`mutator.py`)
- **Observed Defect**: Reconstructing terminal before/after snippets using naive string `.replace(old_val, new_val, 1)` caused display corruption when the replaced value occurred as a substring inside an earlier variable name (e.g. mutating constant `3` to `4` in `is_py3 = _ver[0] == 3` displayed as `is_py4 = _ver[0] == 3`).
- **Architectural Decision**: Replaced whole-line substring replacements with AST node source column tracking (`col_offset` to `end_col_offset`) and token boundary slicing, ensuring the exact AST node being mutated is what is visually reflected in reports.

### 5. Baseline Collection Failure Isolation & Distinct Exit Codes (`mutator.py`, `reporter.py`, `cli.py`)
- **Observed Defect**: When a repository's test suite failed to collect or execute before mutation testing began (e.g. missing dependencies, unbuilt C/Rust extensions in `pydantic`, or OS-specific missing timezones in `marshmallow`), DeployProof reported `Score: 0.0%`, making broken environments indistinguishable from legitimate test-suite quality failures.
- **Architectural Decision**:
  - Implemented baseline failure-to-collect detection (pytest exit codes 2/3/4, `ModuleNotFoundError`, `ImportError`, conftest crashes) before any mutants are generated.
  - Omitted the mutation score entirely (`score = None`) in text and JSON outputs.
  - Output explicit diagnostic guidance: `"Could not run test suite — tests failed to execute before any mutation testing began"` with the underlying exception details.
  - Assigned distinct **exit code `2`** to environment/runner errors, allowing CI/CD pipelines to differentiate environment blockers from verification gate failures (exit code `1`) and clean passing runs (exit code `0`).

### 6. Signal-Safe Disk Restoration & Atomic Cleanup (`mutator.py`)
- **Observed Defect**: While standard `try ... finally` blocks guarantee file restoration during normal Python exception handling and `KeyboardInterrupt`, hard process terminations (e.g. `SIGINT` from Ctrl+C during long-running tests, `SIGTERM` from process supervisors, or `SIGBREAK` in Windows consoles) could bypass the Python unwind stack and leave mutated source files on disk.
- **Architectural Decision**:
  - Maintained global state tracking the currently mutated file path and original unmutated content (`_CURRENT_MUTATED_FILE`, `_CURRENT_ORIGINAL_CONTENT`).
  - Registered dedicated OS signal handlers for `SIGINT`, `SIGTERM`, and `SIGBREAK` (available on Windows where Ctrl+Break generates `SIGBREAK` rather than `SIGINT`).
  - Registered an `atexit` fallback hook as defense-in-depth against sudden process termination.
  - Ensured any restoration failure during signal handling prints an immediate, visible warning to `sys.stderr` rather than failing silently.

### 7. Sandbox Snapshot Liveness Probing & Concurrency Safety (`mutator.py`)
- **Observed Defect**: When running multiple concurrent `deployproof check` instances (e.g. parallel terminals or audits), the startup routine `cleanup_stale_deployproof_temp_dirs()` checked if temporary directories were orphaned using POSIX `os.kill(pid, 0)`. On Windows, `os.kill(pid, 0)` is invalid and raises `OSError: [WinError 87] The parameter is incorrect`, causing the cleaner to falsely conclude that active sibling processes were dead and delete their worker sandboxes mid-run (producing 435 `[Errno 2] No such file or directory` runner errors).
- **Architectural Decision**:
  - On Windows, replaced `os.kill(pid, 0)` with the Win32 API (`kernel32.OpenProcess` with `PROCESS_QUERY_LIMITED_INFORMATION` and `kernel32.GetExitCodeProcess`), accurately detecting live Windows processes and preventing active sandbox deletion.
  - Added a defensive self-healing fallback in `_run_single_mutant_in_sandbox`: if `target_file` is ever missing from a worker sandbox, it automatically restores the missing file directly from the pristine `snapshot_dir` rather than erroring out.

### 8. Full-Repository Mode Runtime & Correctness Boundary
- **Observed Defect / Evaluation**: When auditing massive third-party codebases with heavy network/socket tests (`requests`), full-repo sweeps require ~65–75 minutes across all 795 mutants.
- **Architectural Decision**:
  - Confirmed via research that further narrowing test files on modules whose coverage falls back to shared integration test suites (`test_requests.py`) is fundamentally unsound in Python due to dynamic dispatch, monkeypatching, and transitive coverage.
  - Established that `--full-repo` mode's fallback behavior is correct and final: correctness and true mutation score accuracy take strict precedence over synthetic speedups (documented in `FUTURE_SCOPE.md`). The fast path remains diff-scoped `deployproof check` (2–5 seconds).

### 9. Multi-Worker Parallel Sandboxing Engine & Trade-Off Architecture (`mutator.py`, `cli.py`)
- **Motivation**: Full repository audits (`--full-repo`) and large multi-file refactors generate hundreds of mutants. Running test suites sequentially scales linearly with the test runtime ($O(\text{mutants} \times \text{test\_duration})$), taking 30–60 minutes.
- **Architectural Decision**:
  - Implemented `ProcessPoolExecutor`-based parallelization with PID-keyed temporary sandbox directories (`worker_<PID>`).
  - Isolated pytest cache roots (`--override-ini=cache_dir=...`) and basetemp roots (`--basetemp=...`) per worker to eliminate file locking, cache corruption, and test state leakage.
  - Set `DEPLOYPROOF_WORKER=1` in subprocess environments to prevent recursive cleanup routines from deleting sibling worker sandboxes.
- **Trade-Off Boundaries & Usage Guidance**:
  - **Diff-Scoped Checks (1–3 files, < 20 mutants)**: Defaults to sequential in-place mutation. Spawning isolated sandboxes and copying the repository tree introduces 1–2s of snapshot overhead, whereas in-place sequential execution finishes in **2–5s total**.
  - **Large Diffs (100+ mutants) & Full-Repo Audits**: Users supply `--workers N` (or default to auto-detected CPU cores capped at 8) for near-linear multi-core acceleration.
  - **Disk Space & I/O Consideration**: Running $N$ workers creates $N$ copies of the repository in `tempfile.gettempdir()` ($N \times \text{repo size}$). On disk-constrained systems, worker count should be capped (e.g. `--workers 2` or `--workers 4`).

### 10. In-Memory AST Mutation Schemata & Zero Disk I/O (`mutator.py`)
- **Motivation**: Writing modified files to disk on Windows NTFS for hundreds of mutants created filesystem I/O bottlenecks and process start delays.
- **Architectural Decision**:
  - Implemented in-memory AST schemata compilation where all mutants for a file are injected into a single AST with conditional gates: `if os.environ.get("__DEPLOYPROOF_MUTANT__") == "42":`.
  - Mutants switch dynamically in warm Python memory, eliminating file thrashing and disk locking completely.

### 11. Actionable Self-Healing Test Synthesizer (`synthesizer.py`)
- **Motivation**: Developers diagnosing surviving mutants often struggle to write precise boundary or fallback assertions from scratch.
- **Architectural Decision**:
  - Built an AST-driven test synthesizer that inspects function signatures, parameter type annotations, and AST mutation diffs.
  - Generates targeted `pytest` unit tests with automated class instantiation (`obj = ClassName()`), async/await handling (`@pytest.mark.asyncio`), dictionary missing-key fallbacks, and asymmetric string token verification.

### 12. Standard `pyproject.toml` Configuration Engine (`cli.py`)
- **Motivation**: Eliminating config file sprawl by consolidating configuration into standard PEP 518 `pyproject.toml` files.
- **Architectural Decision**:
  - Added native `[tool.deployproof]` parsing via `tomllib` with transparent 4-tier precedence: CLI flags > `.deployproof.json` > `pyproject.toml` `[tool.deployproof]` > defaults.

### 13. Interactive Quick-Fix Mode with Non-TTY Safety (`interactive.py`, `cli.py`)
- **Motivation**: Enabling developers to inspect and apply self-healing tests directly inside their terminal without manual copy-pasting.
- **Architectural Decision**:
  - Built interactive terminal review prompts (`deployproof check -i`) supporting `[Y/n/q/all]` choices.
  - Implemented `sys.stdin.isatty()` safety verification so unattended CI/CD runs never block or hang waiting for human input.

### 14. GitHub Actions Native Workflow & Step Summary Integration (`ci.py`)
- **Motivation**: Providing teams adopting DeployProof in CI with rich PR dashboards and visual annotations without third-party plugins.
- **Architectural Decision**:
  - Emits GitHub workflow commands (`::error file=...,line=...::` and `::warning file=...,line=...::`) directly into CI stdout.
  - Appends formatted verification summary dashboard tables to `$GITHUB_STEP_SUMMARY`.
