# DEV.to Article Guide

---

## 1. Post Title (Copy and paste into "New post title here..."):
Why 100% Test Coverage is Deceptive (And How We Made Python Mutation Testing Run in 2s)

---

## 2. Tags (Copy and paste into "Add up to 4 tags..."):
python, testing, opensource, programming

---

## 3. Main Article Body (Copy everything below this line into the article editor):

We've all seen pull requests boasting 90%+ or even 100% line coverage. Everything looks green, the tests pass in CI, and the PR gets merged.

A few days later, a subtle logic bug blows up production.

How does this happen? **Because line coverage measures execution paths, not assertion quality.**

With the explosion of AI coding assistants (Copilot, Cursor, Claude), generating tests has become trivial. But AI assistants routinely generate boilerplate tests that execute functions without asserting true invariants:

```python
def test_calculate_discount():
    # Executes every line in calculate_discount(), giving 100% line coverage!
    result = calculate_discount(price=100, is_vip=True)
    assert result is not None  # Never asserts the actual discount math!
```

That test passes with flying colors while touching 100% of the function's lines. But if a bug inverts `price * 0.8` to `price * 1.5`, the test still passes!

---

## The Gold Standard: Mutation Testing

The true metric of test suite integrity is **mutation testing**:

1. An engine modifies your code’s Abstract Syntax Tree (AST) — swapping `==` to `!=`, `<` to `>=`, or replacing return values with `None`.
2. It runs your test suite against each generated "mutant."
3. If your tests **fail**, the mutant is **killed** (your tests assert true correctness).
4. If your tests **pass**, the mutant **survived** (your test coverage is hollow).

### The Bottleneck: Mutation Testing is Painfully Slow

Traditional mutation testing tools like `mutmut` test your entire repository. On a codebase with hundreds of mutants, running test suites repeatedly takes **20 to 60+ minutes**.

Because of that latency, mutation testing has remained an expensive, rarely run overnight CI job rather than an active pre-commit or pre-push quality gate.

---

## The Solution: DeployProof and Diff-Scoped AST Mutation

I built **[DeployProof](https://github.com/SVSPraveen/DeployProof)** to solve the latency problem.

Instead of mutating your entire codebase, DeployProof:
1. Parses your active `git diff` against your base branch or uncommitted working tree.
2. Translates the modified line spans into their specific **AST subtrees**.
3. Generates and executes isolated mutations **strictly on the newly written or modified logic**.

By scoping mutations directly to touched code, DeployProof drops the feedback loop down to **2 to 5 seconds**. You get instant, deterministic proof of whether your new code has genuine assertion backing before you push:

```text
$ deployproof check

[Target Discovery]
  Target Files: 1 (src/auth/tokens.py)
  Test Files:   1 (tests/test_tokens.py)

[Mutation Engine] (diff-scoped)
  Generated Mutants: 6
  Killed:            6
  Survived:          0
  Mutation Score:    100.0%

[Gate Result] PASSED (duration: 2.14s)
```

---

## 4 Other Pre-Push Hygiene Gates

While building the diff-scoped AST engine, I added 4 critical sanity checks that standard linters miss:

* **Dependency Hallucination & Slopsquatting Defense**: AI coding tools frequently introduce dependencies that do not exist on public PyPI. DeployProof queries the official PyPI JSON API before push to verify every new package in `requirements.txt` or inline imports actually exists.
* **Shannon Entropy Secret Scanning**: Catches accidentally tracked `.env` files, leaked OpenAI/Anthropic/AWS API keys, and bearer tokens introduced in session diffs using entropy analysis.
* **Control Flow & Swallowed Exceptions**: Detects and blocks dangerous blanket `except Exception: pass` anti-patterns that hide runtime failures, as well as unverified mock fixtures.
* **GhostApproval Symlink Defense**: Traps repository sandbox-escaping symlinks before commits can reach CI.

---

## Deep Multi-Worker Audits

If you want to audit your entire repository, DeployProof includes a parallel multi-worker engine:

```bash
deployproof check --full-repo --workers 8
```

It uses a `ProcessPoolExecutor` where each worker runs in an isolated, PID-keyed filesystem sandbox (`worker_<PID>`) with dedicated `--override-ini=cache_dir=...` and separate `--basetemp=...` pytest roots to scale across CPU cores without lock contention or state leaks.

---

## Privacy & Zero Telemetry

DeployProof runs **100% locally on your machine**.

There is zero telemetry, zero analytics, and zero external servers. The only outbound network call it makes is querying the public PyPI JSON API to check if a newly imported package exists.

---

## Getting Started

DeployProof is free, open-source (MIT licensed), and available on PyPI.

### Installation

```bash
# Recommended: Isolated global CLI install
pipx install deployproof

# Or via standard pip
pip install deployproof
```

### Run Checks

```bash
# Check active git diff (2–5s)
deployproof check

# Output machine-readable JSON for CI/CD pipelines
deployproof check --json
```

---

## Try It & Share Feedback

DeployProof has been verified against major open-source repositories including `requests`, `click`, and `colorama`.

* **GitHub**: [https://github.com/SVSPraveen/DeployProof](https://github.com/SVSPraveen/DeployProof)
* **PyPI**: [https://pypi.org/project/deployproof/](https://pypi.org/project/deployproof/)

If you test it out on your repositories, drop a comment below with your thoughts, edge cases, or feature requests! If you find it useful, a star on GitHub is always appreciated! ⭐
