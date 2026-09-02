# DeployProof

> Deterministic pre-push quality & security gate for modern Python codebases: In-memory AST mutation testing, credential scanning, and self-healing test synthesis. Built for human engineering teams and AI-assisted workflows alike.

[![PyPI version](https://img.shields.io/badge/pypi-v1.1.15-007ec6.svg)](https://pypi.org/project/deployproof/)
[![Python versions](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-3776ab.svg)](https://pypi.org/project/deployproof/)
[![CI](https://github.com/SVSPraveen/deployproof/actions/workflows/ci.yml/badge.svg)](https://github.com/SVSPraveen/deployproof/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-265%20passed-2ea44f.svg)](https://github.com/SVSPraveen/deployproof)
[![Stress Tests](https://img.shields.io/badge/stress%20tests-14%2F14%20passed-2ea44f.svg)](stress_fixtures/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-DeployProof%20Portal-6366f1.svg)](https://svspraveen.github.io/deployproof/)

---

> 📖 **[View the Complete Documentation & Interactive Product Portal](https://svspraveen.github.io/deployproof/)**

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

Pre-check clean: 100% of tested basic mutations caught.
```

### Advanced Mutation Operators: DeployProof vs Mutmut vs Cosmic Ray

DeployProof features an enterprise-grade AST mutation engine specifically engineered for modern Python applications, AI-assisted development, and instantaneous pre-commit gates:

| Mutation Category | Operator Transformation | Why It Catches Hard Bugs | DeployProof | mutmut | Cosmic Ray |
|---|---|---|:---:|:---:|:---:|
| **Statement Deletion** | `return val` &rarr; `return None`<br>`raise Exc` &rarr; `pass`<br>`assert cond` &rarr; `pass`<br>`call()` &rarr; `pass` | Proves tests assert returned objects, enforce error branches, and verify side-effect calls. | **Yes** | **Yes** | **Yes** |
| **String Boundary** | `"admin"` &rarr; `"XXadminXX"`<br>`""` &rarr; `"XX"` | Exposes tests that pass only because strings are truthy or never strictly asserted. Docstrings preserved. | **Yes** | **Yes** | Partial |
| **Argument Swapping** | `func(a, b)` &rarr; `func(b, a)` | Catches signature confusion bugs when parameters share types (e.g. `(user_id, account_id)`). | **Yes** | No | No |
| **Async / Await Dropping** | `await coro()` &rarr; `coro()` | Exposes unawaited coroutine leaks in modern FastAPI, Starlette, and asyncio code. | **Yes** | No | No |
| **Context Manager Bypass** | `with lock:` &rarr; *bare body*<br>`async with txn:` &rarr; *bare body* | Proves test suite verifies locks, transaction boundaries, and resource cleanup. | **Yes** | No | No |
| **Dict Fallback Removal** | `d.get(k, default)` &rarr; `d.get(k, None)` | Catches implicit fallback assumptions where tests never verify default values. | **Yes** | No | No |
| **Decorator Removal** | `@auth_required` &rarr; *(stripped)*<br>`@lru_cache` &rarr; *(stripped)* | Proves tests verify authentication, caching, validation, and rate-limiting wrappers. | **Yes** | Partial | No |
| **Loop Control** | `break` &harr; `continue` | Exposes untested loop termination criteria and infinite iteration risks. | **Yes** | No | No |
| **Unary Inversion** | `not x` &rarr; `x`<br>`-x` &rarr; `+x`<br>`~x` &rarr; `x` | Catches inverted boolean flags, negative coordinate shifts, and bitwise flags. | **Yes** | **Yes** | **Yes** |
| **Comparison & Identity** | `>=` &rarr; `>`, `<` &rarr; `<=`, `==` &rarr; `!=`<br>`in` &rarr; `not in`, `is` &rarr; `is not` | Detects off-by-one boundary regressions and inverted collection filters. | **Yes** | **Yes** | **Yes** |
| **Git Diff Speed** | **2 – 5 Seconds** *(Diff-Scoped + Fail-Fast)* | Instant feedback in pre-commit hooks and local developer workflows. | **Yes** | Hours | Hours |
| **All-in-One Security** | **AST SAST + Leaked Secrets + CVEs + Slopsquatting** | Complete security & test integrity gate in a single tool and report. | **Yes** | No | No |

### Enterprise AST SAST Scanner (OWASP Top 10 Coverage)

DeployProof includes a zero-dependency, high-precision AST SAST engine built natively into the pre-push gate, covering the most critical Python security risks:

| Rule ID | Vulnerability Class | OWASP Category | CWE | Severity | Example Pattern Detected |
|---|---|---|---|:---:|---|
| **`DP-SAST-001`** | **Arbitrary Code Execution** | A03:2021-Injection | CWE-95 | `CRITICAL` | `eval(expr)`, `exec(user_code)`, `__import__(name)` |
| **`DP-SAST-002`** | **Command Injection** | A03:2021-Injection | CWE-78 | `CRITICAL` | `os.system(cmd)`, `os.popen(cmd)`, `pty.spawn(cmd)` |
| **`DP-SAST-003`** | **Subprocess Command Injection** | A03:2021-Injection | CWE-78 | `HIGH` | `subprocess.run(cmd, shell=True)` |
| **`DP-SAST-004`** | **Insecure Deserialization** | A08:2021-Integrity | CWE-502 | `CRITICAL` | `pickle.loads(b)`, `marshal.loads(b)`, `shelve.open(p)` |
| **`DP-SAST-005`** | **Unsafe YAML Deserialization** | A08:2021-Integrity | CWE-502 | `HIGH` | `yaml.load(text)` without `SafeLoader`, `yaml.unsafe_load()` |
| **`DP-SAST-006`** | **SQL Injection (SQLi)** | A03:2021-Injection | CWE-89 | `HIGH` | `cursor.execute(f"SELECT * WHERE id={id}")` |
| **`DP-SAST-007`** | **Cross-Site Scripting (XSS) / SSTI** | A03:2021-Injection | CWE-79 | `HIGH` | `Markup(user_input)`, `render_template_string(f"...")` |
| **`DP-SAST-008`** | **Path Traversal / Arbitrary File Read** | A01:2021-Access Control | CWE-22 | `HIGH` | `open(f"/data/{filename}")`, `shutil.rmtree("/tmp/" + id)` |
| **`DP-SAST-009`** | **Insecure Cryptographic Algorithms** | A02:2021-Crypto | CWE-327 | `MEDIUM` | `hashlib.md5()`, `hashlib.sha1()`, `Crypto.Cipher.DES` |
| **`DP-SAST-010`** | **Disabled TLS/SSL Verification** | A05:2021-Misconfiguration | CWE-295 | `HIGH` | `requests.get(url, verify=False)`, `ssl._create_unverified_context()` |
| **`DP-SAST-011`** | **Production Debug / Global Bindings** | A05:2021-Misconfiguration | CWE-489 | `HIGH` | `app.run(host="0.0.0.0", debug=True)` |
| **`DP-SAST-012`** | **Insecure Randomness for Secrets** | A07:2021-Auth | CWE-338 | `MEDIUM` | `token = random.randint(...)` (instead of `secrets.token_hex`) |
| **`DP-SAST-013`** | **XML External Entity (XXE)** | A08:2021-Integrity | CWE-611 | `MEDIUM` | `ElementTree.parse(user_xml)` without `defusedxml` |

---

### Complete CLI Commands & Flags Reference

DeployProof provides a rich command-line interface with fine-grained control over every gate:

#### Core Commands

| Command | Syntax | Description | Default |
|---|---|---|---|
| **Check (Default Gate)** | `deployproof check [options]` | Runs all 7 deterministic pre-push verification gates on the modified files in the current git working tree session. | Evaluates git working tree diff against `HEAD` |
| **Initialize Pre-Push Hook** | `deployproof init` | Automatically installs the DeployProof pre-push hook into `.git/hooks/pre-push` and generates an initial `pyproject.toml` `[tool.deployproof]` configuration block. | Installs executable shell/powershell hook |
| **Inspect Diff Scope** | `deployproof diff` | Prints the detected git diff status, modified source files, and test files currently in scope without running tests. | Shows current diff session files |
| **Version** | `deployproof --version` | Displays the current installed version of DeployProof. | Displays `deployproof 1.1.15` |
| **Help** | `deployproof --help` | Displays full interactive command usage and flag descriptions. | Prints CLI help manual |

#### Mutation Testing & Self-Healing Options

| Flag | Short | Type | Description | Default |
|---|---|---|---|---|
| `--threshold <float>` | `-t` | `float` | Minimum mutation score percentage required to pass the verification gate (e.g. `--threshold 85.0`). | `80.0` |
| `--workers <int>` | `-w` | `int` | Number of isolated parallel worker processes for mutation test sandboxes (e.g. `--workers 12`). | Auto-detected CPU count |
| `--heal-tests [path]` | | `path` | Synthesizes verified, ready-to-run pytest test cases with boundary inversion heuristics to kill surviving mutants. Output path defaults to `tests/test_deployproof_healed.py`. | Disabled unless specified |
| `--generate-tests [path]` | | `path` | Alias for `--heal-tests`. | Disabled |
| `--interactive` | `-i` | `flag` | Interactive quick-fix mode. Prompts in the terminal with single-keystroke `[y/N]` confirmation to automatically inspect and append synthesized tests. | Disabled (auto-detects non-TTY for CI safety) |
| `--timeout <float>` | | `float` | Maximum timeout in seconds allowed for a single mutant test execution before killing the process. | `10.0`s |
| `--full-repo` | | `flag` | Audits all tracked Python files across the entire repository root (respecting `.gitignore`), using isolated multi-worker sandboxes. | Diff-scoped to current session |
| `--files <paths...>` | | `paths` | Explicitly evaluate specific files or directories, completely bypassing git diff resolution. | Git working tree diff |
| `--base <ref>` | | `string` | Base git reference (branch, commit hash, or tag) to calculate diff against (e.g. `--base origin/main`). | Auto-detected upstream ref |
| `--wsl` | | `flag` | Delegates mutation testing to native Linux environment inside Windows Subsystem for Linux (WSL). | Native OS execution |

#### Security & Quality Gates

| Flag | Description | Default |
|---|---|---|
| `--sast` / `--no-sast` | Enable or disable the AST-based OWASP Top 10 static security analysis scanner. Detects SQLi, command injection, insecure deserialization, path traversals, etc. | Enabled (`true`) |
| `--scan-git-history` / `--no-scan-git-history` | Scan past git commits using Shannon entropy analysis to catch committed API keys, tokens, and private credentials. | Enabled (`true`) |
| `--history-depth <int>` | Number of past git commits to analyze when `--scan-git-history` is active. | `50` commits |
| `--check-cve` / `--no-check-cve` | Query the open OSV (Open Source Vulnerabilities) database in real time for known CVE advisories affecting dependencies. | Enabled (`true`) |
| `--strict-mocks` / `--no-strict-mocks` | Fail the gate (exit code 1) if modified tests introduce mock imports (`unittest.mock`, `mocker`, `monkeypatch`), proving real behavior instead of mocked stubs. | Disabled (`false`) |
| `--strict-error-handling` / `--no-strict-error-handling` | Fail the gate (exit code 1) if bare `except:`, swallowed exceptions (`except Exception: pass`), or unreachable dead code are detected. | Disabled (`false`) |

#### Reporting, CI/CD & Configuration

| Flag | Short | Description | Default |
|---|---|---|---|
| `--json` | | Output structured machine-readable JSON containing all findings across all 7 verification gates. Ideal for custom CI pipelines, IDE extensions, and dashboards. | Human-readable terminal output |
| `--github-actions` | `--ci` | Emit inline GitHub Actions annotations (`::error file=...,line=...::`, `::warning::`) on PR diff lines and write a complete Markdown dashboard to `$GITHUB_STEP_SUMMARY`. | Auto-detected when `GITHUB_ACTIONS=true` |
| `--config <path>` | | Explicit path to a `pyproject.toml` or custom configuration file. | Auto-discovers `pyproject.toml` in repo root |

### Machine-Readable Output (`--json`)

DeployProof provides a stable structured JSON schema for CI/CD pipelines, IDEs, and automation:

```bash
deployproof check --json
```

#### JSON Output Schema

```json
{
  "version": "1.1.15",
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

## What It Checks (The 7 Verification Gates)

- **Gate 1: In-Memory Schemata Mutation Testing** — Mutates AST operators (`>=`, `==`, `and`, `or`, `*`, numeric constants, string boundaries) and switches mutants in warm RAM (`__DEPLOYPROOF_MUTANT__`), completely bypassing disk I/O.
- **Gate 2: Actionable Self-Healing Test Synthesis** — When mutants survive, `--heal-tests` and `-i` synthesize ready-to-run `pytest` unit tests with argument inference, class method instantiation, and boundary value checks to eliminate gaps.
- **Gate 3: AST OWASP Top 10 SAST Scanner** — Scans AST syntax trees for critical security flaws (SQL injection, command execution with `shell=True`, insecure deserialization, SSRF, hardcoded JWT keys).
- **Gate 4: Secrets & 50-Commit Git History Scanner** — Scans modified files and past 50 git commits for hardcoded API keys (OpenAI, Anthropic, AWS, GitHub, Stripe, private keys) and high-entropy secrets using Shannon entropy analysis.
- **Gate 5: Dependency CVE & Slopsquatting Defense** — Cross-references dependencies against the OSV vulnerability database and queries PyPI JSON API to detect hallucinated LLM packages.
- **Gate 6: CWE-61 Symlink Sandbox Escape Gate** — Resolves symbolic links and flags any whose target escapes the repository root (GhostApproval sandbox traversal defense).
- **Gate 7: Control Flow & Swallowed Exceptions Gate** — AST detector for bare `except:` without re-raise, silently swallowed exceptions (`except Exception: pass`), dead code, and mock leaks (`--strict-mocks`, `--strict-error-handling`).

## Configuration (`pyproject.toml`)

DeployProof natively supports standard PEP 518 `pyproject.toml` configuration under `[tool.deployproof]`:

```toml
[tool.deployproof]
threshold = 85.0
workers = 8
timeout = 15.0
strict_mocks = true
strict_error_handling = true
sast_scanning = true
history_secrets_scanning = true
cve_scanning = true
generate_tests = "tests/test_deployproof_healed.py"
```

## CI/CD & Pre-Commit Integration

### GitHub Actions
Add `.github/workflows/deployproof.yml` to automatically emit PR inline annotations and visual Markdown step summaries:

```yaml
name: DeployProof Gate
on: [push, pull_request]

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 50
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -e . && pip install deployproof pytest
      - run: deployproof check --github-actions --workers 4
```

### Pre-Commit Framework (.pre-commit-config.yaml)
```yaml
repos:
  - repo: https://github.com/SVSPraveen/deployproof
    rev: v1.1.15
    hooks:
      - id: deployproof-check
```

## Status & Roadmap

- **Current (v1.1.15):** In-Memory AST Schemata Mutation Testing, Actionable Self-Healing Test Synthesizer (`--heal-tests`), Interactive Quick-Fix Mode (`-i`), `pyproject.toml` `[tool.deployproof]` configuration engine, GitHub Actions native inline annotations and `$GITHUB_STEP_SUMMARY` dashboard, `.pre-commit-hooks.yaml` support, Full Repository Audit Mode (`--full-repo`) with isolated multi-worker sandboxes, AST OWASP Top 10 SAST scanner, 50-commit git history secrets scanner, OSV CVE database verification, GhostApproval symlink sandbox escape detector, **265 unit tests**, and complete `/docs` product portal.
- **Next:** Reverse test-to-source dependency mapping (see `FUTURE_SCOPE.md`), SARIF 2.1.0 report exporter, and multi-language mutation rule packs.

## Contributors & Acknowledgements

* **[SVS Praveen](https://github.com/SVSPraveen)** — Creator & Lead Architect
* **[nube-k](https://github.com/nube-k)** — Core Contributor

## Contributing

Issues and pull requests are welcome. Open an issue first for significant changes so the approach can be discussed before implementation.

## License

MIT. See [LICENSE](LICENSE).

---

*Created & Architected by [SVS Praveen](https://github.com/SVSPraveen) · [Portfolio](https://svspraveen.vercel.app/) · [LinkedIn](https://www.linkedin.com/in/svs-praveen-s/)*


