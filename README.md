# DeployProof

> A pre-push verification tool for AI-assisted codebases: mutation testing, credential scanning, sandbox-escape detection, and dependency hallucination checks.

<!-- Once the package is published to PyPI, replace the static badge below with:
     [![PyPI version](https://img.shields.io/pypi/v/deployproof)](https://pypi.org/project/deployproof/) -->
[![PyPI](https://img.shields.io/badge/PyPI-not_yet_published-lightgrey)](https://pypi.org/project/deployproof/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/deployproof)](https://pypi.org/project/deployproof/)
[![CI](https://github.com/SVSPraveen/deployproof/actions/workflows/ci.yml/badge.svg)](https://github.com/SVSPraveen/deployproof/actions/workflows/ci.yml)

---

## Why This Exists

AI-assisted development introduces failure modes that standard tools miss: test suites with high line coverage but near-zero mutation scores, hardcoded credentials generated in passing, symlinks that deceive approval prompts into escaping the repository sandbox, and package names hallucinated by LLMs that don't exist on PyPI. DeployProof catches these at the pre-push stage, before they reach CI or production.

## Install

```bash
pip install deployproof
```

Requires Python 3.10+.

## Quickstart

Initialize in your repository:

```bash
deployproof init
```

Run all verification checks against changes in the current session:

```bash
deployproof check
```

Output includes a section for each check — symlink scan, secrets scan, dependency scan, and mutation score — with a pass/fail line at the bottom. Exit code is non-zero on any finding that should block a push.

## What It Checks

- **Mutation Score** — Mutates AST operators (`>=`, `==`, `and`, `or`, `*`, numeric constants, comparisons) in modified files and runs your test suite against each mutant. Reports surviving mutants and a percentage score. Does not use line coverage.
- **Secrets and Credentials** — Scans modified files for hardcoded API keys (OpenAI, Anthropic, AWS, GitHub, Stripe, private keys) and tracked `.env` files using pattern matching and entropy analysis.
- **Symlink and Sandbox Escape** — Resolves symbolic links and flags any whose target escapes the repository root (CWE-61 / CWE-451). Catches the class of path-traversal trick used in the GhostApproval disclosure (Wiz Research, July 2026).
- **Dependency and Slopsquatting** — For each new import or manifest entry introduced in the diff, queries the PyPI JSON API and checks registration age. Packages that don't exist (HTTP 404) are flagged HIGH RISK; packages registered within the last 30 days are flagged MEDIUM RISK. Network errors are reported as UNKNOWN — never silently treated as safe.

## What This Doesn't Do

- **Not a full-repo audit.** Checks are scoped to files changed in the current session (git diff). Files you haven't touched are not re-evaluated.
- **Python only.** Mutation testing and import extraction currently support Python files only. Other languages are not scanned.
- **No auto-fix.** DeployProof reports findings; it does not modify your code, rewrite imports, or suggest patches.
- **No IDE plugin yet.** There is no VS Code extension or JetBrains plugin. The CLI is the interface. IDE integration is on the roadmap.

## See It Catch Real Bugs

Clone this repository and run the standalone stress-test suite to see DeployProof evaluate 7 planted edge cases:

```bash
python stress_fixtures/run_stress_tests.py
```

Fixtures cover weak test suites, zero-test orphan modules, planted OpenAI/AWS credentials, and GhostApproval sandbox-escape traps.

## Status & Roadmap

- **Current (v0.1.0):** Diff-scoped AST mutation testing, secrets scanner, GhostApproval symlink sandbox-escape detector, PyPI dependency hallucination / slopsquatting scanner, and Tier 2 CI verification via GitHub Actions (mutmut).
- **Next:** Multi-language mutation support and expanded ecosystem rule packs.

## Contributing

Issues and pull requests are welcome. Open an issue first for significant changes so the approach can be discussed before implementation.

## License

MIT. See [LICENSE](LICENSE).

---

*Created by [SVS Praveen](https://github.com/SVSPraveen) · [Portfolio](https://svspraveen.vercel.app/) · [LinkedIn](https://www.linkedin.com/in/svs-praveen-s/)*
