# DeployProof

**DeployProof** is a **Python CLI** tool for **AI-code verification** — it catches what 100% line coverage misses by running **in-memory AST mutation testing** on your git diff before any commit reaches CI. Created by [SVS Praveen](https://github.com/SVSPraveen).

```bash
pip install deployproof
```

[![PyPI version](https://img.shields.io/badge/pypi-v1.1.17-007ec6.svg)](https://pypi.org/project/deployproof/)
[![Python versions](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-3776ab.svg)](https://pypi.org/project/deployproof/)
[![CI](https://github.com/SVSPraveen/deployproof/actions/workflows/ci.yml/badge.svg)](https://github.com/SVSPraveen/deployproof/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-278%20passed-2ea44f.svg)](https://github.com/SVSPraveen/deployproof)
[![Stress Tests](https://img.shields.io/badge/stress%20tests-14%2F14%20passed-2ea44f.svg)](stress_fixtures/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-DeployProof%20Portal-6366f1.svg)](https://svspraveen.github.io/deployproof/)

<p align="center">
  <img src="https://raw.githubusercontent.com/SVSPraveen/deployproof/main/assets/deployproof-hero.png" alt="DeployProof: Pre-Push Quality & Security Gate" width="100%">
</p>

---

> 📖 **[View the Complete Interactive Product Portal & Live Docs](https://svspraveen.github.io/deployproof/)**  
> 💡 *Curious why we built it this way? Read our architectural rationale in **[DECISIONS.md](DECISIONS.md)**.*

---

## Contents
- [Why This Exists](#why-this-exists)
- [How It Compares: DeployProof vs. Mutmut vs. Cosmic Ray](#how-it-compares)
- [Installation](#installation)
- [Quickstart & Walkthrough](#quickstart--walkthrough)
- [How It Works](#how-it-works)
- [The Verification Gates](#the-verification-gates)
- [CI/CD & Pre-Commit Integration](#cicd--pre-commit-integration)
- [Configuration (`pyproject.toml`)](#configuration-pyprojecttoml)
- [Full Documentation & CLI Reference](#full-documentation--cli-reference)

---

## Why This Exists

The standard AI-code workflow produces tests that pass CI but don't actually verify anything. A test suite at 90% line coverage can have a mutation score near zero — meaning almost any change to the logic under test goes completely undetected.

DeployProof runs **in-memory AST mutation testing** scoped to your git diff. It mutates operators, constants, and control-flow in warm RAM (no disk writes), runs your tests against each mutant, and fails the push if surviving mutants exceed your threshold — in the time it takes to read a Slack message.

It also ships with a set of companion security gates for the failure modes that mutation testing doesn't catch on its own: hardcoded secrets, OWASP-class SAST patterns, hallucinated dependencies, and symlink escapes.

> **Privacy guarantee**: DeployProof runs 100% locally. The only outbound requests are read-only: PyPI JSON API (dependency hallucination check) and OSV (CVE lookup, opt-out with `--no-check-cve`). No source code, test results, or findings leave your machine.

---

## How It Compares

The core difference from mutmut and Cosmic Ray is *where* the mutation happens. Both of those tools rewrite source files on disk and spawn a fresh test process for every mutant — which is slow and doesn't scope to your diff. DeployProof compiles all mutants into a single conditional AST in warm RAM and only tests the files you actually changed:

| | DeployProof | mutmut | Cosmic Ray |
|---|:---:|:---:|:---:|
| **Mutation engine** | In-memory AST schemata | File rewrite to disk | AST disk rewriting |
| **Scoped to git diff** | **Yes** | No (full repo) | No (full repo) |
| **Self-healing test synthesis** | **Yes** | No | No |
| **Async/await, arg-swap, boundary mutations** | **Yes** | Partial | Partial |
| **Secrets & SAST scanning** | Also included | No | No |
| **Dependency hallucination & CVE checks** | Also included | No | No |
| **Multi-worker sandboxes** | **Yes (`--workers N`)** | No | Distributed (Celery) |
| **GitHub Actions summaries** | **Yes** | No | No |

---

## Installation

```bash
pip install deployproof

# Recommended: isolated environment with global CLI access
pipx install deployproof
```

*Requires Python 3.10+.*

---

## Quickstart & Walkthrough

<p align="center">
  <img src="https://raw.githubusercontent.com/SVSPraveen/deployproof/main/assets/deployproof-terminal-showcase.jpg" alt="DeployProof Terminal Verification Showcase" width="100%">
</p>

### The Problem in Action

Given a newly written function `calculator.py`:

```python
def calculate_discount(price: float, rate: float) -> float:
    if rate > 0.5:
        return price * 0.5
    return price * (1.0 - rate)
```

With an AI-generated test that achieves **100% line coverage** by only asserting a single happy path (`rate = 0.2`):

```python
def test_calculate_discount_basic():
    assert calculate_discount(100.0, 0.2) == 80.0
```

Running `deployproof check` mutates AST operators in memory and immediately exposes that threshold caps and boundaries are unverified:

```
$ deployproof check

Target Scope (1 file evaluated):
  * calculator.py

Local Pre-Check Mutation Verification:
  Score:  57.1% (4/7 mutants killed)
  Status: FAILED (score 57.1% below 80.0%)
  Time:   2.27s

Surviving Mutants (3 unverified changes):
  [1] calculator.py:2  Mutation: Replace numeric constant '0.5' with '1.5'
  [2] calculator.py:3  Mutation: Replace numeric constant '0.5' with '1.5'
  [3] calculator.py:3  Mutation: Replace binary operator '*' with '/'

Pre-check FAILED: Score 57.1% is below threshold 80.0% (3 surviving mutants).
```

### Self-Healing the Test Suite

Run with `--heal-tests` (or interactively with `-i`) to automatically synthesize ready-to-run pytest unit tests that target the exact surviving mutants:

```bash
deployproof check --heal-tests
```

```python
# Generated in tests/test_deployproof_healed.py
def test_calculate_discount_boundary_rate():
    assert calculate_discount(100.0, 0.5) == 50.0

def test_calculate_discount_capped_rate():
    assert calculate_discount(100.0, 0.8) == 50.0
```

Re-running `deployproof check` immediately passes:

```
Local Pre-Check Mutation Verification:
  Score:  100.0% (7/7 mutants killed)
  Status: PASSED (threshold: 80.0%)
  Time:   2.31s

Surviving Mutants: None (All generated mutants caught by test suite)
Pre-check clean: 100% of tested basic mutations caught.
```

---

## How It Works

DeployProof runs in two modes:

### Default: Diff-Scoped Gate (`deployproof check`)
Evaluates **only the files modified in your git diff**. Because mutants are compiled into warm RAM — no disk writes, no file copies — this mode is significantly faster than traditional mutation tools and completes before your attention switches context.

```bash
# Check modified files in your current git diff
deployproof check

# Output structured JSON for IDE tooling or custom pipelines
deployproof check --json

# Enforce strict gates on newly introduced mocks or swallowed errors
deployproof check --strict-mocks --strict-error-handling
```

### Full Repository Audit (`deployproof check --full-repo`)
Evaluates **every tracked Python file** across the entire repository, parallelizing across isolated worker sandboxes:

```bash
deployproof check --full-repo --workers 8
```

### Windows WSL Delegation (`deployproof check --wsl`)
Translates Windows paths (safely quoting spaces), delegates mutation runs to `mutmut` inside a native Linux environment in WSL, and streams results back to your Windows console:

```bash
deployproof check --wsl
```

> ⚙️ **One-Time WSL Setup**: `wsl bash -c "python3 -m venv ~/.deployproof-wsl-venv && ~/.deployproof-wsl-venv/bin/pip install mutmut pytest"`  
> *(If WSL is not configured, DeployProof falls back to the native in-memory engine with a notice.)*

---

## The Verification Gates

### Core: Mutation Testing

**Gate 1 — In-Memory AST Mutation Engine**  
Mutates operators (`>=`, `==`, `and`, `or`, `*`), numeric constants, string boundaries, async/await drops, and argument swaps. All mutants are compiled into a single conditional AST and toggled via environment variable — no disk I/O, no file copies.

**Gate 2 — Self-Healing Test Synthesizer**  
Analyzes surviving mutants and synthesizes ready-to-run pytest unit tests with inferred parameter signatures, class method instantiation, and boundary value fixtures. Run with `--heal-tests` or `-i` for interactive mode.

---

### Also Included: Security Gates

These run alongside the mutation pass and catch categories of failure that mutation testing alone doesn't cover:

**Gate 3 — AST OWASP Top 10 SAST Scanner**  
Zero-dependency static scanner: SQL injection, `shell=True`, `os.system`, insecure deserialization (`pickle`, `yaml.load`), path traversals, disabled SSL.

**Gate 4 — Secrets & Git History Scanner**  
Shannon entropy scan of session files and the past 50 git commits: OpenAI, Anthropic, AWS, GitHub, and Stripe keys.

**Gate 5 — Dependency CVE & Slopsquatting Defense**  
Cross-references requirements against OSV for known CVEs; queries PyPI JSON API in real time to catch hallucinated package names.

**Gate 6 — CWE-61 Symlink Sandbox Escape**  
Resolves symlinks and blocks any whose target falls outside the repository root.

**Gate 7 — Control Flow & Error Handling**  
Detects bare `except:`, swallowed exceptions, unreachable dead code, and mock leaks (`--strict-mocks`, `--strict-error-handling`).

---

## Architecture & Design Rationale

Curious why in-memory AST schemata instead of file rewrites, or how the dual-tier model works?

👉 **Read [DECISIONS.md](DECISIONS.md)** for the complete technical design document, performance trade-off analyses, and threat models.

---

## CI/CD & Pre-Commit Integration

### GitHub Actions
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

### Pre-Commit Framework (`.pre-commit-config.yaml`)
```yaml
repos:
  - repo: https://github.com/SVSPraveen/deployproof
    rev: v1.1.17
    hooks:
      - id: deployproof-check
```

---

## Configuration (`pyproject.toml`)

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

---

## Full Documentation & CLI Reference

For exhaustive CLI flag references, JSON output schemas, and advanced customization:

👉 **[Explore the Interactive DeployProof Portal & Docs Site](https://svspraveen.github.io/deployproof/)**

---

## Contributing

Issues and pull requests are welcome. Open an issue first for significant changes so the approach can be discussed before implementation.

## License

MIT. See [LICENSE](LICENSE).

---

*DeployProof is created & architected by [SVS Praveen](https://github.com/SVSPraveen) — Python developer focused on AI-code verification tooling · [Portfolio](https://svspraveen.vercel.app/) · [LinkedIn](https://www.linkedin.com/in/svs-praveen-s/)*
