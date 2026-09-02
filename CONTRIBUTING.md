# Contributing to DeployProof

Thank you for your interest in contributing to DeployProof! DeployProof is an open-source, deterministic pre-push verification tool for Python (and multi-language roadmap) codebases.

## Core Philosophy & Guardrails

1. **100% Deterministic & Reproducible**: Verification must never rely on non-deterministic LLM calls in the evaluation path. The same code input must yield the exact same mutation and security score across every run.
2. **Local-First & Zero Telemetry**: DeployProof runs strictly on the developer's local machine and sends no telemetry, source code, test output, or findings to external servers. The only outbound network requests permitted are read-only HTTP GET queries to the official PyPI registry to verify package existence and registration age.
3. **No Breaking Performance Regressions**: Diff-scoped mutation verification (`deployproof check`) must execute in **2 to 5 seconds** for typical 1–3 file changes.

---

## Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/SVSPraveen/deployproof.git
   cd deployproof
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv .venv
   # Windows (PowerShell):
   .venv\Scripts\Activate.ps1
   # Linux/macOS:
   source .venv/bin/activate
   ```

3. **Install dependencies and editable package**:
   ```bash
   pip install -e ".[dev]"
   ```

4. **Run the full test suite**:
   ```bash
   pytest
   ```

---

## Running Verification & Stress Tests

Before submitting a pull request, run DeployProof against itself:

```bash
# Verify modified working tree files
deployproof check

# Run with parallel workers
deployproof check --workers 4
```

---

## Submitting Pull Requests

1. **Branching**: Create a focused feature or bugfix branch (`feature/your-feature` or `fix/issue-description`).
2. **Tests Required**: Every bug fix or new feature must include accompanying unit tests under `tests/`.
3. **Deterministic AST Rules**: If adding new mutation operators or static control-flow rules, ensure AST transformation logic has corresponding test fixtures under `stress_fixtures/`.
4. **Clean Commits**: Write clear, descriptive commit messages following the Conventional Commits specification.

---

## Code of Conduct

Please maintain a welcoming, respectful, and constructive environment for all contributors.

---

## Core Contributors

* **[SVS Praveen](https://github.com/SVSPraveen)** — Project Creator & Lead Architect
* **[nube-k](https://github.com/nube-k)** — Core Contributor

