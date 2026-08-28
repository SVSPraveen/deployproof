# DeployProof

A deterministic AI-code deployability checker for fast local pre-checks and authoritative CI gates.

## Installation

```bash
pip install deployproof
```

For local development:

```bash
git clone https://github.com/SVSPraveen/deployproof.git
cd deployproof
pip install -e .[dev]
```

## Basic Usage

Run local deployability pre-checks against current session changes:

```bash
deployproof check
```

> **Performance Note**: For files exceeding ~300 LOC, mutation pre-check may take several minutes due to sequential single-process test execution. Parallelization is planned for a future release.

## Features

- **Smart Session Diff Scoping**: Automatically identifies uncommitted working-tree edits or branch commits (`--base <ref>`) without whole-repo overhead. Test files are safely excluded from mutation targets.
- **Two-Tier Mutation Testing**: Fast local AST pre-check (Tier 1) for rapid developer iteration with an authoritative `mutmut` verification gate in GitHub Actions CI (Tier 2).
- **Pre-Push Secrets & Credentials Scanner**: Scans all session diff files (`.py`, `.env`, `.json`, `.yml`, `.yaml`, `.toml`, config files) for hardcoded API keys (OpenAI, AWS, GitHub, Google, Slack, Stripe, HuggingFace, private keys) and high-entropy secret assignments, safely redacting values in terminal reports (`sk****************yz`).
- **Symlink & GhostApproval Sandbox-Escape Scanner**: Identifies symlinks and verifies whether the resolved target escapes the repository boundary (CWE-61 / CWE-451, CVE-2026-50549), preventing deceptive tool approvals.
- **Optional WSL Bridge (Windows)**: Run authoritative `mutmut` locally via WSL with `deployproof check --wsl`.

## Optional WSL Integration (Windows)

To run verified `mutmut` locally on Windows via WSL, create a dedicated Linux virtualenv:

```bash
wsl bash -c "python3 -m venv ~/.deployproof-wsl-venv && ~/.deployproof-wsl-venv/bin/pip install mutmut pytest"
```

Then execute:

```bash
deployproof check --wsl
```

If WSL or the Linux venv is not configured, DeployProof automatically falls back to the local Tier 1 pre-check without crashing.

## License

MIT License. See [LICENSE](LICENSE) for details.
