# DeployProof — Growth Scope (Post-Launch)

Core rule: nothing in Stage N+1 starts until Stage N has real evidence behind it. No stage is time-boxed - it ends when its exit criteria are actually met, however long that takes.

## Stage 0 — Current State (as of v1.0.0 launch)
v1.0.0, Python-first, deterministic verification (diff-scoped mutation testing, secrets scanning, PyPI slopsquatting detection, control-flow checks, symlink sandbox-escape detection, and multi-worker full-repo audits). Verified against major open-source codebases (`click`, `requests`, `colorama`). Zero external users. Zero external contributors. Zero public posts.

## Stage 1 — Launch Week
Actions: publish the proof artifact (terminal recording showing a real bug DeployProof catches that pytest misses), post to Hacker News and r/Python using the durable "deterministic verification" positioning, not an AI-hype-only framing.
Exit criteria to Stage 2: real installs from strangers AND at least one piece of unsolicited real feedback (a bug report, a question, a feature request, or someone saying it caught something real).

## Stage 2 — Listen, Don't Build (first weeks after launch)
Rule: do not build new features from imagination during this stage, even if excited. Track every piece of real user feedback in one running log.
Exit criteria to Stage 3: the SAME request or pain point shows up from 3+ independent real users - that's the signal for what to build next, not before.

## Stage 3 — First External Contributor
Prerequisite: `CONTRIBUTING.md` and `SECURITY.md` are in place so the project is welcoming and ready for external open-source contributors.
This stage represents genuine external validation — when a developer who is not the author meaningfully contributes to the codebase.
Exit criteria to Stage 4: first external PR merged, or sustained engagement from multiple outside developers.

## Stage 3.5 — Enterprise Readiness Signals
- Baseline-first state management for secrets scanning (`.deployproof-baseline` file, delta-only enforcement on legacy repos) — Trigger: someone reports DeployProof being unusable on a large legacy codebase due to historical findings.
- Institutional governance signals (naming a backup maintainer, or pursuing PyPA/OpenSSF affiliation) — Trigger: real enterprise inbound interest, not before.
- Diff-scoped mutation testing architecture (already implemented) is confirmed by independent research as the correct choice versus full-repo mutation testing, which is the primary reason mutmut stayed niche — validation note (no action needed).

## Stage 4 — Sustained Cadence
Small, real releases driven by actual fixes and actual demand patterns from Stage 2/3 - not roadmap padding. Periodic build-log content (following the Week 3 pattern from the original adoption research) to keep visibility active, not just a one-time launch post.

## Stage 5 — Expansion Decisions (only after Stage 3+ evidence exists)
- Multi-language support: separate sibling repos (deployproof-js, etc.), same brand, only after Python shows real sustained external adoption - not before.
- CI/PR integration (SARIF, deployproof-action): build only once a real user asks, per the trigger already defined in FUTURE_SCOPE.md.
- Any enterprise-facing feature: build only after an actual inbound enterprise inquiry, never speculatively.
