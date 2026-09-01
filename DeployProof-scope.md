# DeployProof — Architectural Scope & Engineering Specification

*Package: `deployproof` (v1.0.0 on PyPI). Repository: github.com/SVSPraveen/DeployProof. Status: Released September 1, 2026.*

---

## 1. The Empirical Problem & Baseline Findings

Solo and small-team developers ship significant volumes of AI-generated code without the automated review capacity to catch subtle edge cases, security hazards, and hallucinated dependencies. Documented industry findings establish the following baseline challenges:

- **Elevated Issue Density**: CodeRabbit's analysis of 470 open-source pull requests found AI-co-authored code carries **~1.7x more issues overall** than human-only code — with logic and correctness errors 75% more common, error-handling gaps ~2x more common, and security vulnerabilities up to **2.74x higher for XSS specifically**.
- **The Code Coverage Illusion**: A peer-reviewed study on LLM-generated tests (arXiv:2506.02954, HumanEval-Java) found test suites achieving 100% line/branch coverage scored only **4% on mutation testing** — executing every statement while failing to verify boundary conditions, threshold limits, or logic gates (such as leap-year date edge cases).
- **Dependency Hallucination ("Slopsquatting")**: Open-source models hallucinate package names at an average rate of **21.7%**, with some CodeLlama-family configurations exceeding **33%** (Spracklen et al., 576,000-sample study). A 2026 follow-up (arXiv:2605.17062) re-evaluating frontier models (Claude, GPT-4, Gemini, DeepSeek) found the rate compressed to **~4.6–6.1%**. Crucially, **43% of hallucinated names recur across identical prompts**, enabling attackers to pre-register malicious packages on PyPI/npm.
- **Agent Sandbox-Escape Vectors ("GhostApproval")**: Wiz Research disclosed symlink-based escape vectors (CWE-61 combined with UI decoy display CWE-451) across six major AI IDEs. Current patch and disclosure status: Cursor is patched (CVE-2026-50549, CVSS 9.8, fixed in v3.0), AWS Language Servers are patched (CVE-2026-12958, CVSS 7.8), Google Antigravity is patched. Both Anthropic and Augment stated they dispute that symlink traversal in their agents constitutes an agent vulnerability (with a related Claude Code sandbox-escape tracked as CVE-2026-39861). Windsurf remains unpatched.
- **Secrets Leaks in AI Commits**: Commits co-authored specifically by Claude Code leak secrets at **roughly 2x the general baseline** (GitGuardian 2026: 3.2% of Claude-Code-co-authored commits vs. 1.5% across all public GitHub commits).

**Core Principle**: LLM-based verifiers share the exact cognitive blind spots and training distributions of the LLMs that generated the code. Verification must remain **100% deterministic, local, and math/AST-driven**, with zero LLM calls in the evaluation path.

---

## 2. Competitive Landscape & Market Differentiation

- **Ratchet CLI** (`ratchetcli.com`, `github.com/kcemate/ratchet`): Focused exclusively on TypeScript/JavaScript repositories. Covers security linting, type holes, and coverage gaps, but does not provide real mutation testing, slopsquatting registration-age defense, or AI-IDE-specific symlink/config escape scanning. Paid tiers gate autonomous test fixing and release gates ($19–$79/mo). Python remains completely open ground.
- **blastradius-cli** (PyPI, Apache 2.0): Multi-language static dependency analyzer and impact scorer with a 10-tool MCP server. Excellent for static impact analysis, but does not execute mutation tests or scan for secrets/slopsquatting.
- **Mutahunter** (AGPL-3.0): Uses LLMs to generate context-aware mutants ("fault injection"). While innovative, LLM-generated mutants reintroduce the structural issue where the verifier shares the generator's blind spots. DeployProof uses deterministic AST operator mutations.
- **slopcheck**: Inspects dependency existence at the install boundary. DeployProof differentiates by analyzing package metadata and registration age to detect freshly registered malicious packages.

**Verified Market Niche**: Zero-cost, Python-first (and multi-language roadmap) deterministic pre-push verification combining diff-scoped AST mutation testing, credential scanning, slopsquatting defense with PyPI age analysis, control-flow checks, and GhostApproval symlink traps in a single local CLI with zero paywalls.

---

## 3. Tool Currency Verification

All wrapped and upstream tools verified against live package registries as of late 2026:

| Tool | Ecosystem | Current Status | Integration Strategy |
|---|---|---|---|
| `mutmut` | Python | Active (v3.x line, PyPI) | Native AST Engine fallback & benchmarking |
| `cosmic-ray` | Python | Active | Alternative Python mutation baseline |
| `StrykerJS` | JS/TS | Active (v7.x, Vitest/Tap) | Phase 4 JS/TS runner |
| `PIT / pitest` | Java / JVM | Active (Maven Central) | Phase 4 JVM plugin |
| `cargo-mutants` | Rust | Active (crates.io) | Phase 4 Rust cargo runner |
| `Gremlins` | Go | Pre-1.0 (0.x) | Phase 4 experimental wrapper (budget extra integration time) |
| `mutant` | Ruby | Active (v0.15.x) | Phase 4 Ruby runner |
| `Infection` | PHP | Active (GitHub/Composer) | Phase 4 PHP runner |
| `blastradius-cli` | Multi | Active (PyPI) | Reused for impact mapping / reverse dependency graph |

---

## 4. End-to-End Developer Workflow

1. **Install Once**: `pip install deployproof` (zero accounts, zero API keys, 100% local execution).
2. **Initialize Repository**: `deployproof init` auto-detects project structure and configures the test runner.
3. **Execute Pre-Push Gate**: `deployproof check` evaluates newly modified files in the active git diff (completes in **2–5 seconds**).
4. **Inspect Deterministic Findings**: Reviews mutation score, exact surviving mutant line numbers, hardcoded secrets, and dependency age flags in plain terminal output or JSON format (`deployproof check --json`).
5. **Close the Feedback Loop**: Developers fix edge cases or supply the surviving mutant list back to their coding agent to prompt missing test assertions.
6. **Optional Full Audits & CI**: Run `deployproof check --full-repo` for scheduled codebase sweeps or wire `deployproof check` into pre-commit / GitHub Actions.

---

## 5. Core Architecture & Verification Modes

```
Developer Finishes Coding Session / Pre-Push Trigger
                        │
                        ▼
     ┌─────────────────────────────────────┐
     │ 1. Git Diff Scope Resolver          │
     │    (Smart Working Tree & Cascade)   │
     └──────────────────┬──────────────────┘
                        │
                        ▼
     ┌─────────────────────────────────────┐
     │ 2. Parallel & Static Audit Suite    │
     │  - Symlink / Sandbox Escape Scanner │
     │  - Secrets & Credentials Scanner    │
     │  - PyPI Dependency & Age Scanner    │
     │  - Control Flow & Error Analyzer    │
     │  - Mock Introduction Gate           │
     └──────────────────┬──────────────────┘
                        │
                        ▼
     ┌─────────────────────────────────────┐
     │ 3. AST Mutation Verification Engine │
     │  - In-Place Diff Scoping (2-5s)     │
     │  - Multi-Worker Sandbox Engine      │
     └──────────────────┬──────────────────┘
                        │
                        ▼
     ┌─────────────────────────────────────┐
     │ 4. Deterministic Reporter & Gate    │
     │  - Exit 0 (PASS), 1 (FAIL), 2 (ERR) │
     └─────────────────────────────────────┘
```

### Execution Modes & Performance Profile:

| Execution Mode | Target Scope | Typical Duration | Intended Use Case |
| :--- | :--- | :--- | :--- |
| **`deployproof check`** | Git Diff (1–3 modified files) | **2 – 5 seconds** | Fast local pre-commit, active AI IDE loops, pre-push sanity checks. |
| **`deployproof check --workers 8`** | Large Diff (100+ mutants) | **1 – 3 minutes** | Large feature branch reviews, wide refactors. |
| **`deployproof check --full-repo`** | Small Repo (< 100 mutants, sequential) | **30s – 2 minutes** | Single-core / lightweight auditing. |
| **`deployproof check --full-repo --workers 8`** | Small Repo (< 100 mutants, 8 workers) | **15 – 30 seconds** | Rapid full baseline verification. |
| **`deployproof check --full-repo`** | Medium Repo (200–500 mutants, sequential) | **15 – 35 minutes** | Unconstrained single-thread verification. |
| **`deployproof check --full-repo --workers 8`** | Medium Repo (200–500 mutants, 8 workers) | **3 – 7 minutes** | Release validation, pre-tag quality gates. |
| **`deployproof check --full-repo`** | Heavy Lib (`requests`, 800 mutants, sequential) | **60 – 85 minutes** | Deep overnight / weekly sweep. |
| **`deployproof check --full-repo --workers 8`** | Heavy Lib (`requests`, 800 mutants, 8 workers) | **12 – 18 minutes** | High-throughput multi-core CI release builds. |

---

## 6. Parallel Multi-Worker Sandbox Architecture (`--workers N`)

### Technical Mechanism:
1. **Initial Project Snapshot**: DeployProof creates a clean, atomic snapshot of the repository in the system's temporary directory.
2. **PID-Keyed Process Sandboxing**: For $N$ workers, DeployProof initializes $N$ independent directories (`worker_<PID>`). Each worker process operates in its own isolated filesystem sandbox with dedicated pytest cache (`--override-ini=cache_dir=...`) and temp root (`--basetemp=...`).
3. **Task Distribution**: Mutants are partitioned across workers using a `ProcessPoolExecutor`. Each mutant is applied and tested inside the isolated worker directory, leaving the working tree completely untouched.
4. **Signal-Safe Cleanup**: Dedicated signal hooks (`SIGINT`, `SIGTERM`, `SIGBREAK`) and `atexit` handlers ensure all temporary worker sandboxes are wiped on process exit or user cancellation.

### Advantages & Trade-Off Analysis:

#### Advantages:
- **Near-Linear Compute Scaling**: Distributes heavy test execution suites across all available CPU cores, reducing 30-minute sweeps to 5–8 minutes.
- **Process & Test Isolation**: Prevents test-suite state pollution, SQLite locking conflicts, and `.pytest_cache` contention between concurrent test runs.

#### Disadvantages & When NOT to Use:
- **Snapshot I/O Overhead on Small Diffs**: Setting up worker sandboxes and copying the repository snapshot takes ~1–2 seconds. For typical 1–2 file diffs (5–15 mutants), in-place sequential mutation is faster (**2–5s total**).
- **Temporary Disk Footprint**: Running $N$ workers consumes $N \times \text{repository size}$ in temporary storage. On disk-constrained runners, cap workers to 2 or 4.
- **Fixed-Port Test Collisions**: Tests that bind hardcoded socket ports (e.g. `localhost:8000`) without dynamic allocation will experience port collisions when run in parallel workers.

---

## 7. Security & Privacy Model

DeployProof enforces strict local execution guarantees:
- **100% Local Processing**: All source code parsing, AST mutation, credential scanning, and control-flow checks run strictly on the local developer machine.
- **Zero Outbound Telemetry**: No source code, diffs, test logs, mutant scores, or discovered secrets are ever transmitted to any external server.
- **Controlled Registry Inspection**: The only outbound network requests made by DeployProof are read-only HTTP GET queries to the official PyPI JSON API (`https://pypi.org/pypi/<pkg>/json`) to verify that newly introduced dependencies exist and evaluate package registration timestamps for slopsquatting analysis.

---

## 8. Multi-Language Roadmap

| Phase | Milestone | Focus Areas |
|---|---|---|
| **Phase 1** | **Python Core (v1.0.0)** | Native AST mutation engine, Git diff cascading, credential scanner, GhostApproval symlinks, slopsquatting age detector. |
| **Phase 2** | **Reverse Dependency Mapping** | Blast-radius AST indexer connecting modified test suites back to unmodified source files. |
| **Phase 3** | **CI & SARIF Integration** | SARIF 2.1.0 report generation, GitHub Actions pre-merge gating. |
| **Phase 4** | **Multi-Language Expansion** | StrykerJS (JS/TS), PIT (Java), cargo-mutants (Rust), Gremlins (Go). |
| **Phase 5** | **Native IDE Extensions** | Post-session verification plugins for Claude Code, Cursor, and Google Antigravity. |

---

## 9. Verification & Stress-Test Layer

Every gate in DeployProof is continuously validated against dedicated test fixtures in `stress_fixtures/`:
1. `untested_calculator.py` — Planted surviving mutant detection (verifies that 100% line coverage fails mutation testing).
2. `symlink_escape/` — GhostApproval-style directory traversal and UI spoofing fixture.
3. `poisoned_rules/` — Malicious instruction injection in `.cursorrules` / `CLAUDE.md`.
4. `slopsquatting/` — Hallucinated dependency fixtures with anomalous registration timestamps.
5. `hardcoded_secrets/` — High-entropy API keys (OpenAI, AWS, GitHub, Stripe, Private Keys).

---

## 10. Honest Risks & Technical Boundaries

- **Mutation Testing Compute Cost**: Full repository mutation testing scales with test suite runtime ($O(\text{mutants} \times \text{runtime})$). DeployProof keeps daily loops fast (2–5s) via diff-scoping. Full-repo sweeps are positioned for periodic audits, not fast pre-commit checks.
- **Slopsquatting Maintenance**: Registry metadata schema updates and new package registries require ongoing maintenance.
- **Disputed Vulnerability Classes**: GhostApproval symlink traversal vectors are contested by some vendors (e.g. Anthropic, Augment). DeployProof maintains precision by reporting the exact path discrepancy (displayed path vs. resolved target) rather than making subjective vendor vulnerability claims.
- **Growth Cadence**: Developer infrastructure tools grow through peer trust and verifiable accuracy rather than viral consumer curves.
