# DeployProof

> Deterministic pre-push quality & security gate for modern Python codebases: AST mutation testing, credential scanning, sandbox-escape detection, mock-usage alerts, swallowed-exception checks, and dependency hallucination defense. Built for human engineering teams and AI-assisted workflows alike.

[![PyPI version](https://img.shields.io/badge/pypi-v1.1.1-007ec6.svg)](https://pypi.org/project/deployproof/)
[![Python versions](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-3776ab.svg)](https://pypi.org/project/deployproof/)
[![CI](https://github.com/SVSPraveen/DeployProof/actions/workflows/ci.yml/badge.svg)](https://github.com/SVSPraveen/DeployProof/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-111%20passed-2ea44f.svg)](https://github.com/SVSPraveen/DeployProof)
[![Stress Tests](https://img.shields.io/badge/stress%20tests-11%2F11%20passed-2ea44f.svg)](stress_fixtures/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Why This Exists

Modern software development — whether crafted by human engineering teams or generated through AI coding assistants — introduces subtle failure modes that standard linters and line-coverage metrics completely miss:

* **Deceptive Test Suites**: Test suites boasting 90%+ line coverage that never assert true correctness, masking near-zero mutation scores.
* **Accidental Credential Exposure**: Hardcoded API keys, bearer tokens, or service credentials generated in passing or pasted into tests.
* **Sandbox Escape Risks**: Symlinks that deceive tool approval prompts into breaking outside the repository sandbox.
* **Silently Swallowed Exceptions**: Blanket `except Exception: pass` anti-patterns that hide critical runtime bugs.
* **Dependency Hallucinations & Slopsquatting**: Package names invented by LLMs or mistyped dependencies that don't exist on public PyPI.

DeployProof serves as an uncompromising, deterministic pre-push gate that validates code quality, test integrity, and security locally before any commit reaches CI or production.

> **Privacy & Security Guarantee**: DeployProof runs 100% locally on your machine. It makes zero outbound network calls, except for querying the official PyPI registry (JSON API) to verify that newly introduced dependencies exist and are not hallucinated. DeployProof sends no source code, telemetry, test results, or secret findings to any external server.

## Install

```bash
# Recommended — installs into an isolated environment, exposes the CLI globally
pipx install deployproof

# Or via pip into your current environment
pip install deployproof
```

Requires Python 3.10+. If you don't have `pipx`, install it with `pip install pipx` then run `pipx ensurepath`.

## How to Use DeployProof

DeployProof provides two distinct modes of operation. We believe in total transparency about execution costs:

### 1. Diff-Scoped Pre-Push Gate (`deployproof check`) — *Primary Fast Workflow*
Evaluates **only the files modified in your active session or git diff** (1–3 files typically). Because only newly edited AST nodes are mutated, it executes in **2 to 5 seconds** in local developer loops, pre-commit hooks, and pre-push gates.

```bash
# Fast daily check: verifies modified files in your current working tree / git diff (2-5s)
deployproof check

# Output structured JSON for automation or IDE tooling
deployproof check --json

# Enforce strict gates on newly introduced mocks or swallowed errors
deployproof check --strict-mocks --strict-error-handling
```

### 2. Full Repository Audit Mode (`deployproof check --full-repo`) — *Thorough Codebase Audits*
Evaluates **every tracked Python file across the entire repository**. Because mutation testing generates hundreds or thousands of mutants and runs the test suite against each one in isolated multi-worker sandboxes, full repository scans take real, honest compute time:

```bash
# Run a full-repository audit across all tracked files
deployproof check --full-repo

# Customize the parallel worker process count (defaults to auto-detected CPU count capped at 8)
deployproof check --full-repo --workers 8
```

#### Real-World Timing Expectations:

> [!NOTE]
> **Estimated Timings Disclaimer**: The durations below are empirical estimates based on benchmark runs across various open-source projects (such as `requests`, `click`, and `colorama`). Actual execution time may be **higher or lower** depending on your specific test suite execution speed (e.g., pure unit tests vs. heavy integration/database tests), test runner timeout settings (`--timeout`), hardware profile (CPU core clock speed, available RAM), and codebase complexity.

| Scan Mode | Target Scope | Estimated Duration* | Intended Use Case |
| :--- | :--- | :--- | :--- |
| **`deployproof check`** | Git Diff (1–3 modified files) | **2 – 5 seconds** | Local pre-commit, active AI IDE coding loops, pre-push sanity checks. |
| **`deployproof check --workers 8`** | Large Multi-File Diff (100+ mutants) | **1 – 3 minutes** | Large feature branch reviews, refactors. |
| **`deployproof check --full-repo`** | Small Repo (< 100 mutants, sequential) | **30s – 2 minutes** | Single-core / lightweight auditing. |
| **`deployproof check --full-repo --workers 8`** | Small Repo (< 100 mutants, 8 workers) | **15 – 30 seconds** | Rapid full baseline verification. |
| **`deployproof check --full-repo`** | Medium Repo (200–500 mutants, sequential) | **15 – 35 minutes** | Unconstrained single-thread verification. |
| **`deployproof check --full-repo --workers 8`** | Medium Repo (200–500 mutants, 8 workers) | **3 – 7 minutes** | Release validation, pre-tag quality gates. |
| **`deployproof check --full-repo`** | Heavy / Network Lib (`requests`, 800 mutants) | **60 – 85 minutes** | Deep overnight / weekly sweep. |
| **`deployproof check --full-repo --workers 8`** | Heavy / Network Lib (`requests`, 800 mutants) | **12 – 18 minutes** | High-throughput multi-core CI release builds. |

### Parallel Multi-Worker Sandboxing (`--workers N`)

DeployProof includes a built-in multi-process execution engine (`ProcessPoolExecutor`) for parallel mutation testing. You can supply `--workers <N>` to both diff-scoped checks and full-repo audits:

```bash
# Parallelize a large uncommitted diff across 8 worker processes
deployproof check --workers 8

# Full repository audit distributed across 8 worker processes
deployproof check --full-repo --workers 8
```

#### How Parallel Sandboxing Works:
1. **Snapshot Creation**: DeployProof takes an initial atomic snapshot of your project into a clean temporary directory.
2. **PID-Keyed Sandboxes**: Each worker process receives its own dedicated filesystem sandbox (`worker_<PID>`), with an independent `pytest` cache (`--override-ini=cache_dir=...`) and separate temporary directory (`--basetemp=...`).
3. **Zero Mutation Leaks**: Mutants are generated and executed inside individual worker sandboxes in parallel. The working tree is untouched, and signal handlers (`SIGINT`, `SIGTERM`, `SIGBREAK`) ensure sandboxes are cleanly purged upon completion or interruption.

#### Advantages & When to Use:
* **Large Diff / Full Repo Speedup**: Near-linear execution scaling across CPU cores for batches with 50+ mutants, cutting 30-minute sweeps down to 5–8 minutes.
* **Process & Cache Isolation**: Eliminates cross-test state leakage, shared database locking, and `.pytest_cache` collisions between concurrent workers.

#### Trade-offs & When NOT to Use:
* **Small Daily Diffs (1–3 files)**: Do NOT use `--workers` for small 2-line edits. Spawning isolated sandboxes and copying file trees incurs ~1–2 seconds of snapshot overhead. Sequential in-place mutation executes in **2–5 seconds** with zero snapshot overhead.
* **Disk Space & I/O Overhead**: Running $N$ workers copies the repository snapshot $N$ times into temporary storage ($N \times \text{repo size}$ in `tempfile.gettempdir()`). On disk-constrained environments, use fewer workers (e.g. `--workers 2` or `--workers 4`).
* **Subprocess / Port Collisions**: If your test suite binds to fixed network ports (e.g. localhost:8080) without dynamic port selection, parallel workers running tests concurrently may trigger port conflicts. Use isolated ports or run sequentially in such environments.

#### Hardware & Memory Sizing Architecture (RAM & CPU Optimization):

DeployProof's parallel sandboxing engine scales throughput directly with **available physical RAM** and **logical CPU cores**. Because test execution is CPU-bound and sandbox file I/O is memory-bound, hardware capacity dictates performance:

```
Total Memory Required ≈ Base OS Overhead (~2 GB) + [ N_workers × (Worker Process RSS + OS Page Cache Footprint) ]
```

##### 1. Why More RAM Directly Maximizes Verification Speed:
* **Zero-Latency In-Memory OS Page Cache**: When physical RAM comfortably exceeds the aggregate working set of all $N$ workers, the operating system holds all sandbox file trees, compiled `.pyc` modules, and pytest test fixtures directly in the **RAM page cache**. File mutations and test imports achieve sub-millisecond execution with zero physical NVMe/SSD read/write contention.
* **Elimination of Page-Fault Swapping**: If total RAM is insufficient for the requested `--workers N`, the OS kernel is forced to page memory to disk (`pagefile.sys` on Windows or swap partitions on Linux). Page thrashing introduces severe disk queue latency that can degrade multi-process test throughput by 5× to 10×. Higher RAM guarantees that all workers remain 100% compute-active in physical memory.

##### 2. Per-Worker Memory Consumption Profile:
* **Python Runtime & AST Engine**: ~35 MB RSS per worker.
* **Pytest Test Suite & Dependencies**: ~50 MB to 150 MB RSS per worker (depending on framework imports like FastAPI, Django, SQLAlchemy, or Requests).
* **Sandbox Working Directory Snapshot**: ~15 MB to 50 MB in OS file cache per worker.
* **Total Allocation per Worker Process**: **~100 MB to 250 MB RAM per worker**.

##### 3. Hardware Sizing & Safe Allocation Matrix:

| Installed System RAM | Recommended Worker Flag | Memory Consumed by DeployProof | System Headroom Remaining | Intended Verification Profile |
| :--- | :--- | :--- | :--- | :--- |
| **2 GB – 4 GB** | `deployproof check` *(Sequential)* | ~120 MB total | High (~2.5 GB free) | Ultra-lightweight diff checks; single-core laptops. |
| **8 GB** | `--workers 4` | ~0.8 GB – 1.0 GB | Safe (~5.5 GB free) | Standard local feature branches and medium diffs. |
| **16 GB** | **`--workers 8` to `--workers 16`** | **~1.6 GB – 3.2 GB** | **Abundant (~12.8 GB free)** | **Full CPU core saturation; rapid multi-file diffs & full-repo sweeps.** |
| **32 GB+** | `--workers 16` to `--workers 32` | ~3.5 GB – 6.5 GB | Enterprise headroom | Heavy monorepos, multi-thousand mutant CI sweeps. |

##### 4. Diff Scoped vs Full Repo Memory Comparison:

| Metric | Git Diff (`deployproof check --workers 8`) | Full Repo (`deployproof check --full-repo --workers 8`) | Technical Rationale |
| :--- | :--- | :--- | :--- |
| **Concurrent OS Processes** | 8 worker processes | 8 worker processes | **Identical** — `ProcessPoolExecutor` only executes $N$ workers concurrently. |
| **Worker Process RSS** | ~80 MB – 120 MB per process | ~120 MB – 180 MB per process | **Slightly higher** — Full repo sweeps import broader test suites and transitive frameworks into Python's `sys.modules`. |
| **Sandbox Snapshot Cache** | ~15 MB per sandbox | ~30 MB – 60 MB per sandbox | **Higher** — Full repo snapshots clone all tracked repo files into temporary directories. |
| **Total Memory with 8 Workers** | **~1.0 GB – 1.4 GB** | **~1.6 GB – 2.2 GB** | Modest increase; easily accommodated by standard 8 GB/16 GB machines. |
| **Total Memory with 16 Workers** | **~1.8 GB – 2.5 GB** | **~3.0 GB – 3.8 GB** | Complete 16-core saturation while leaving 12+ GB RAM free on 16 GB systems. |

##### 5. Minimum vs Recommended System Requirements:
* **Absolute Minimum System RAM**: **2 GB** (for default sequential diff-scoped `deployproof check`).
* **Minimum System RAM for Multi-Worker Mode (`--workers 4`)**: **4 GB**.
* **Recommended System RAM for Max-Throughput Parallel Mode (`--workers 8` or `16`)**: **16 GB** (provides sufficient headroom to keep 8 to 16 Python subprocesses and their entire sandboxes resident in physical memory).

Output includes a section for each check — symlink scan, secrets scan, dependency scan, mock detection, control flow analysis, and mutation score — with a pass/fail line at the bottom. 

### Exit Codes:
* `0` — **PASSED**: All verification checks passed and mutation score meets threshold.
* `1` — **FAILED**: Code quality or security gate triggered (mutation score below threshold, untested files, hardcoded secrets, sandbox-escape symlinks, hallucinated packages, or strict flags).
* `2` — **ERROR**: Test environment failure (test suite failed to collect or execute before mutation testing began due to missing dependencies or broken imports).

### Example Walkthrough

Given a newly written function `calculator.py`:

```python
def calculate_discount(price: float, rate: float) -> float:
    if rate > 0.5:
        return price * 0.5
    return price * (1.0 - rate)
```

With an AI-generated test that achieves 100% line coverage by only asserting standard discounts (`rate = 0.2`):

```python
def test_calculate_discount_basic():
    assert calculate_discount(100.0, 0.2) == 80.0
```

Running `deployproof check` mutates AST operators and detects that boundary conditions and threshold caps are untested:

```
$ deployproof check

DeployProof - LOCAL PRE-CHECK (approximate) - not the verified score
====================================================================

Target Scope (1 file evaluated):
  * calculator.py

Symlink & Sandbox Escape Scan (CWE-61/CWE-451):
  Clean: No symlinks or sandbox-escape traversal links detected across 1 session file.

Secrets & Credentials Pre-Push Scan:
  Clean: No hardcoded secrets or tracked .env files detected across 1 session file.

Dependency & Slopsquatting Scan (PyPI Registry & Age Analysis):
  Clean: No new external packages introduced across 1 session file.

Mock Usage Introduced (flagged for review):
  Clean: No modified test files in scope.

Control Flow & Error Handling (flagged for review):
  Clean: No bare excepts, swallowed exceptions, or unreachable code detected across 1 session file.

Local Pre-Check Mutation Verification:
  Score:  57.1% (4/7 mutants killed)
  Status: FAILED (score 57.1% below 80.0%) (threshold: 80.0%)
  Time:   2.27s

Skipped Constructs: None (No known unsupported constructs detected)

Surviving Mutants (3 unverified changes):

  [1] calculator.py:2
      Mutation: Replace numeric constant '0.5' with '1.5'
      Original: if rate > 0.5:
      Mutated:  if rate > 1.5:

  [2] calculator.py:3
      Mutation: Replace numeric constant '0.5' with '1.5'
      Original: return price * 0.5
      Mutated:  return price * 1.5

  [3] calculator.py:3
      Mutation: Replace binary operator '*' with '/'
      Original: return price * 0.5
      Mutated:  return price / 0.5

====================================================================
Notice: Local pre-check only. Full verified score runs in CI on push (via mutmut).
Pre-check FAILED: Score 57.1% is below threshold 80.0% (3 surviving mutants).
```

Adding tests for threshold cap (`rate = 0.8`) and exact boundary (`rate = 0.5`) kills all mutants:

```
Local Pre-Check Mutation Verification:
  Score:  100.0% (7/7 mutants killed)
  Status: PASSED (threshold: 80.0%)
  Time:   2.31s

Surviving Mutants: None (All generated mutants caught by test suite)

====================================================================
Notice: Local pre-check only. Full verified score runs in CI on push (via mutmut).
Pre-check clean: 100% of tested basic mutations caught.
```

### CLI Options & Flags

| Flag | Description |
|---|---|
| `deployproof check` | Run all 6 pre-push verification checks (informational warnings for mocks and error handling). |
| `deployproof check --json` | Output structured, machine-readable JSON for CI/CD pipelines, IDEs, and automation. |
| `deployproof check --strict-mocks` | Fail the gate (exit code 1) if new `unittest.mock`, `mocker`, or `monkeypatch` usage is introduced. |
| `deployproof check --strict-error-handling` | Fail the gate (exit code 1) if bare excepts, swallowed exceptions, or dead code are detected. |
| `deployproof check --files <paths...>` | Explicitly evaluate specific files (bypasses git diff). |
| `deployproof check --threshold <float>` | Minimum mutation score percentage required to pass (default: `80.0`). |
| `deployproof check --base <ref>` | Base git ref (branch/commit/tag) to diff against. |
| `deployproof check --full-repo` | Audit all tracked files across the entire repository root (respecting `.gitignore`), using isolated parallel workers. |
| `deployproof check --workers <int>` | Set the number of isolated parallel worker processes for `--full-repo` scans (default: auto-detected CPU count capped at 8). |
| `deployproof check --wsl` | Delegate mutation testing to `mutmut` inside WSL (Windows only). |

> **Note:** `deployproof check --wsl` (Windows only) is newer and less battle-tested than the core checks — [file an issue](https://github.com/SVSPraveen/DeployProof/issues) if you hit something.

### Machine-Readable Output (`--json`)

DeployProof provides a stable structured JSON schema for CI/CD pipelines, IDEs, and automation:

```bash
deployproof check --json
```

#### JSON Output Schema

```json
{
  "version": "1.1.1",
  "status": "passed",
  "summary": {
    "target_files_count": 1,
    "mutation_score": 100.0,
    "threshold": 80.0,
    "secrets_found": 0,
    "symlink_escapes_found": 0,
    "dependency_findings": {
      "high_risk": 0,
      "medium_risk": 0,
      "ok": 1,
      "unknown": 0,
      "unscanned": 0
    },
    "mock_usages_found": 0,
    "control_flow_findings": 0,
    "strict_mocks_active": false,
    "strict_mocks_triggered": false,
    "strict_error_handling_active": false,
    "strict_error_handling_triggered": false
  },
  "scope": {
    "target_files": [
      {
        "file": "app.py",
        "loc": 45,
        "is_large": false
      }
    ]
  },
  "mutation_testing": {
    "score": 100.0,
    "threshold": 80.0,
    "total_mutants": 6,
    "killed_mutants": 6,
    "survived_mutants_count": 0,
    "duration_seconds": 1.2,
    "surviving_mutants": [],
    "skipped_constructs": [],
    "untested_files": []
  },
  "secrets": {
    "clean": true,
    "files_scanned": 1,
    "findings": []
  },
  "symlinks": {
    "clean": true,
    "files_scanned": 1,
    "findings": []
  },
  "dependencies": {
    "clean": true,
    "total_scanned": 1,
    "findings": [],
    "unscanned_sources": []
  },
  "mocks": {
    "clean": true,
    "strict_gate_triggered": false,
    "findings": []
  },
  "control_flow": {
    "clean": true,
    "strict_gate_triggered": false,
    "findings": []
  }
}
```

## What It Checks

- **Mutation Score** — Mutates AST operators (`>=`, `==`, `and`, `or`, `*`, numeric constants, comparisons) in modified files and runs your test suite against each mutant. Reports surviving mutants and a percentage score. Does not use line coverage. Features atomic file restoration protected by `SIGINT`/`SIGTERM`/`SIGBREAK` signal handlers to ensure interrupted runs never leave mutated code on disk.
- **Secrets and Credentials** — Scans modified files for hardcoded API keys (OpenAI, Anthropic, AWS, GitHub, Stripe, private keys) and tracked `.env` files using pattern matching and entropy analysis.
- **Symlink and Sandbox Escape** — Resolves symbolic links and flags any whose target escapes the repository root (CWE-61 / CWE-451). Catches the class of path-traversal trick used in the GhostApproval disclosure (Wiz Research, July 2026).
- **Dependency and Slopsquatting** — For each new import, dynamic import (`importlib.import_module`, `__import__`), or manifest entry (including recursive `-r` includes) introduced in the diff, queries the PyPI JSON API and checks registration age. Packages that don't exist (HTTP 404) are flagged HIGH RISK; packages registered within the last 30 days are flagged MEDIUM RISK.
- **Mock Usage Detection** — Scans test diffs for newly introduced imports or fixture uses of `unittest.mock`, `mocker`, and `monkeypatch`, flagging them for human review with an optional `--strict-mocks` hard gate.
- **Control Flow and Error Handling** — AST-based detector for bare `except:` without re-raise, silently swallowed broad exceptions (`except Exception:` that only `pass` or log/print without re-raising or returning error indicators), and dead/unreachable code following unconditional `return`, `raise`, `break`, or `continue`, with an optional `--strict-error-handling` hard gate.

## What This Doesn't Do
 
- **Test-only diffs are not yet caught.** If a diff modifies or weakens assertions in a test file without changing the corresponding source file, DeployProof currently sees zero modified source lines and passes with 0 mutants evaluated. This is a known gap — see [INVESTIGATION_blastradius.md](INVESTIGATION_blastradius.md) for the reverse-mapping approach being evaluated to close it. Until this lands, DeployProof does not protect against test suites being weakened directly.
- **Diff-scoping vs Full Audits:** Standard `deployproof check` is intentionally scoped strictly to files modified in the active git diff (for 2–5s speed). To audit every file in the entire repository, explicitly pass the `--full-repo` flag.
- **Python only.** Mutation testing and import extraction currently support Python files only. Other languages are not scanned.
- **No auto-fix.** DeployProof reports findings; it does not modify your code, rewrite imports, or suggest patches.
- **No IDE plugin yet.** There is no VS Code extension or JetBrains plugin. The CLI is the interface. IDE integration is on the roadmap.

## See It Catch Real Bugs

Clone this repository and run the standalone stress-test suite to see DeployProof evaluate 11 planted edge cases:

```bash
python stress_fixtures/run_stress_tests.py
```

Fixtures cover weak test suites, zero-test orphan modules, planted OpenAI/AWS credentials, GhostApproval sandbox-escape traps, swallowed exceptions/dead code, and mock-masked broken implementations.

## Status & Roadmap

- **Current (v1.1.1):** Diff-scoped AST mutation testing (with recursive discovery and `SIGINT`/`SIGTERM`/`SIGBREAK` signal-safe disk restoration), **Full Repository Audit Mode (`--full-repo`)** with isolated parallel multi-worker sandboxes and AST import-graph test discovery, baseline test-collection failure isolation with distinct exit code `2`, entropy-driven value-based secrets scanner, GhostApproval symlink sandbox-escape detector, PyPI dependency hallucination / slopsquatting scanner (with import-to-distribution translation, recursive `-r` requirements scanning, and dynamic import detection via `importlib` / `__import__`), mock-introduction detector (`--strict-mocks`), control-flow / swallowed-exception scanner (`--strict-error-handling`), 11/11 launch-day stress test suite, **111 unit tests**, live unbuffered progress streaming, and machine-readable `--json` output.
- **Next:** Reverse test-to-source dependency mapping (see `FUTURE_SCOPE.md`), SARIF 2.1.0 PR annotations, and multi-language mutation rule packs.

## Contributing

Issues and pull requests are welcome. Open an issue first for significant changes so the approach can be discussed before implementation.

## License

MIT. See [LICENSE](LICENSE).

---

*Created by [SVS Praveen](https://github.com/SVSPraveen) · [Portfolio](https://svspraveen.vercel.app/) · [LinkedIn](https://www.linkedin.com/in/svs-praveen-s/)*

