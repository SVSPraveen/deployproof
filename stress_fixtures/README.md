# DeployProof Stress-Test Fixtures

This directory contains standalone, reproducible test fixtures designed to stress-test **DeployProof** against both planted bugs/vulnerabilities and clean control repositories.

---

## Quick Start: Run All Fixtures in One Command

```bash
python stress_fixtures/run_stress_tests.py
```
*(or on Unix: `bash stress_fixtures/run_stress_tests.sh`)*

---

## Fixture Inventory

### 1. Mutation Testing Checks (`mutation/`)

| Fixture | Scenario | Expected Result |
|---|---|---|
| **`01_weak_test_suite`** | `billing.py` with tests that pass basic smoke checks but miss boundary operators (`>=`, `>`, `*`). | **Catches surviving mutants** ($<100\%$ score, pre-check `FAILED`). |
| **`02_strong_test_suite`** | `billing.py` with comprehensive tests covering boundary values and tiers. | **Kills 100% of mutants** ($100.0\%$ score, pre-check `PASSED`). |
| **`03_zero_tests`** | `orphan_service.py` with an unrelated test suite that never touches it. | **Flags untested file distinctly** ($0.0\%$ score, pre-check `FAILED (0 tests collected)`). |

---

### 2. Secrets & Credentials Scanner (`secrets/`)

| Fixture | Scenario | Expected Result |
|---|---|---|
| **`01_clean_repo`** | Standard constants, timeouts, URLs, and JSON configurations. | **0 False Positives** (`Clean: No hardcoded secrets detected`). |
| **`02_planted_secrets`** | Planted `sk-proj-...` OpenAI keys, `AKIA...` AWS access keys, high-entropy bearer tokens, and a tracked `.env` file. | **Flags all credentials + tracked `.env`** (Exit code `1`). |

---

### 3. Symlink & Sandbox-Escape Scanner (`symlinks/`)

| Fixture | Scenario | Expected Result |
|---|---|---|
| **`01_safe_symlink`** | Legitimate in-repo symlink pointing to an internal `config/app.json`. | **0 False Positives** (Verified safe in-repo link). |
| **`02_ghostapproval_escape`** | GhostApproval-class trap (CVE-2026-50549 / CWE-61 / CWE-451): apparent path `config/app_settings.json` points to `../../../../etc/shadow` outside repo root. | **Flags critical sandbox escape** (Exit code `1`, blocks push). |

---

## Core Guarantee

DeployProof does not rely on LLM guessing or stochastic scoring. Every check is deterministic, reproducible, and verifiable via raw AST mutations, regex/entropy credential patterns, and filesystem path traversal analysis.
