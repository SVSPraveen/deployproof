# DeployProof

A deterministic pre-push verification tool that catches untested AI code, leaked credentials, and sandbox escapes before you ship.

Created by [SVS Praveen](https://github.com/SVSPraveen)

## The Problem

AI-assisted development generates code faster than developers can review it, creating measurable blind spots. CodeRabbit's December 2025 analysis of 470 pull requests found AI-co-authored code carried 1.7x more logic and correctness issues than human-written code, while GitGuardian (2026) reported AI-assisted commits leak credentials at roughly double the baseline rate (3.2% vs. 1.5%). Furthermore, standard line coverage is an unreliable proxy for test quality: empirical research (arXiv:2506.02954) demonstrated that test suites achieving 100% line coverage often score as low as 4% on mutation testing, missing fundamental edge cases. Meanwhile, agent sandbox-escape bugs (Wiz Research July 2026 GhostApproval disclosure; CVE-2026-50549, CVE-2026-12958, CVE-2026-39861) demonstrated that approval prompts can be deceived by path traversal symlinks.

## What It Checks

- **Mutation Score (not coverage)**: Mutates session AST operators (`>=`, `==`, `and`, `or`, `*`) to test whether your test suite actually catches broken logic.
- **Secrets and Credentials Scanner**: Intercepts hardcoded API keys (OpenAI, AWS, GitHub, Stripe, private keys) and tracked `.env` files across all session files before push.
- **Symlink and Sandbox-Escape Prevention**: Detects symbolic links whose resolved target escapes the repository root directory (CWE-61 / CWE-451).

## Quickstart

Install from PyPI:

```bash
pip install deployproof
```

Initialize in your repository:

```bash
deployproof init
```

Run verification checks against current session changes:

```bash
deployproof check
```

> **Performance Note**: For files exceeding ~300 LOC, local mutation pre-checks run sequentially in single-process mode and may take several minutes. Parallelized execution is planned for an upcoming release.

## See It Catch Real Bugs

Clone this repository and run the standalone stress-test suite in one command to see DeployProof evaluate 7 planted edge cases:

```bash
python stress_fixtures/run_stress_tests.py
```

See [stress_fixtures/](stress_fixtures/) for documented fixtures covering weak test suites, zero-test orphan modules, planted OpenAI/AWS credentials, and GhostApproval sandbox-escape traps.

## Why Deterministic

DeployProof does not use an LLM in its verification path. A generative model used to check its own output shares the generator's underlying blind spots and hallucination patterns. By relying exclusively on AST mutation, regular expression and entropy scanning, and filesystem path resolution, DeployProof produces reproducible, verifiable pass/fail proofs.

## Positioning & Comparisons

DeployProof focuses on diff-scoped mutation testing and AI-IDE security checks; it does not replicate multi-language dependency impact mapping (handled by tools like `blastradius-cli`) or TypeScript/JavaScript static rule analysis (handled by tools like `Ratchet CLI`).

## Status & Roadmap

- **Current (v0.1.0)**: Diff-scoped Tier 1 AST mutation testing, pre-push secrets scanner, GhostApproval symlink sandbox-escape detector, and Tier 2 CI verification gate via GitHub Actions (`mutmut`).
- **Next**: Parallelized local mutation execution for large files, dependency registration-age analysis to prevent slopsquatting / hallucinated packages, and multi-language mutation support.

## License

MIT License. See [LICENSE](LICENSE) for details.

## Author

SVS Praveen — [github.com/SVSPraveen](https://github.com/SVSPraveen)
