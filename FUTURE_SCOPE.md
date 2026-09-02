# DeployProof — Future Scope Backlog

This is a running list of features that are explicitly NOT being built now — captured so they aren't lost, not because they're scheduled.

---

## Reverse Test-to-Source Dependency Mapping (Highest Priority)

Status: Open / Under Evaluation. Blocked on: architecture & integration path.

What it would involve:
- Closing the single most severe blind spot in DeployProof's core diff-scoping model: when a diff modifies or weakens assertions in a test file (e.g. `tests/test_calculator.py`) without modifying the corresponding application source file (`calculator.py`), diff-scoping currently resolves 0 modified application source files and exits cleanly with 0 mutants evaluated.
- Implementing reverse dependency mapping from modified test files back to their tested source modules, automatically pulling the affected source files into the mutation scope even if the source files themselves were untouched in the diff.
- Implementation path: Evaluated in [INVESTIGATION_blastradius.md](INVESTIGATION_blastradius.md) using `blastradius-cli`'s static dependency graph indexer (`blastradius impact` / `blastradius analyze`), invoked via CLI subprocess with `--json` output, or via an internal reverse AST import graph builder.

Why it matters: This is the primary blind spot in diff-scoped mutation testing — an AI agent or developer can delete critical test assertions without triggering a mutation score penalty.

---

## CI / GitHub PR Integration (Native Integration Shipped in v1.1.14)

Status: Core Native Support Shipped in `v1.1.14` (`src/deployproof/ci.py`).

What was delivered in v1.1.14:
- Native GitHub Actions workflow command emission: `::error file=...,line=...::` and `::warning file=...,line=...::` annotations directly on PR diff lines.
- Automatic Markdown step summary table emission written to `$GITHUB_STEP_SUMMARY`.
- `--github-actions` / `--ci` flag and automated `GITHUB_ACTIONS=true` environment detection.

Future Expansion Backlog:
- Direct SARIF 2.1.0 output format (`--format=sarif` flag) for native GitHub Advanced Security code scanning tab.
- Companion marketplace GitHub Action (`deployproof/deployproof-action`).

---

## License Decision (Resolved)
Confirmed via research: MIT stays. AGPL was briefly considered earlier for anti-cloning protection, but research confirmed AGPL is subject to explicit, documented bans at Google, is classified "Category X" (banned) by the Apache Software Foundation and FINOS, and is auto-rejected by common enterprise dependency-scanning tools (Sonatype, Aikido). Real precedent: ownCloud and Dgraph both abandoned AGPL specifically due to this exact blocker. MIT remains correct - it's pre-approved and passes automated compliance checks at virtually all large organizations. No action needed - this is confirmation of the existing choice, not a change.

---

## Project Governance & Stewardship

OpenSSF Scorecard checks (Maintained, Contributors, Code-Review) feed automated procurement checks at large organizations. Future stewardship milestones include: (1) expanding core contributors, (2) pursuing foundation/fiscal hosting (Python Software Foundation), (3) enterprise support channels. These will be scheduled alongside enterprise customer demand.

---

## Full-Repo Mode Runtime (Resolved, Not a Bug)

Confirmed via research: there is no safe technique to further speed up mutation testing on files whose test coverage falls back to large, slow shared test files (e.g. `auth.py`/`adapters.py` in `requests`, falling back to `test_requests.py`). Three real technical barriers prevent it: (1) `sys.setprofile`-based call-graph tracing would add 10x-50x runtime overhead, defeating the purpose; (2) static call-graph analysis is fundamentally unsound in Python due to dynamic dispatch, decorators, and monkeypatching; (3) even dynamic coverage contexts cannot guarantee correctness on transitively-covered code — narrowing the test set risks silently excluding the one test that would have caught a real mutation, corrupting the mutation score.

Decision: `--full-repo` mode's current behavior (fall back to full test file when direct attribution is ambiguous) is correct and final. ~65-75 minutes for a full mutation sweep on a heavy library like `requests` is an honest cost, not a bug. This is explicitly NOT something to keep optimizing — doing so would trade correctness for speed, which contradicts DeployProof's core value proposition.

The fast path (diff-scoped `deployproof check`, 2-5 seconds) is unaffected by any of this and remains the primary, marketed use case. `--full-repo` is correctly positioned as an occasional, thorough audit mode, not a fast operation.

The sandbox snapshot isolation on Windows is hardened via Win32 PID liveness checking (`kernel32.OpenProcess`/`GetExitCodeProcess`) before snapshot cleanup, eliminating cross-process worker race conditions.
