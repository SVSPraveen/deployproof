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

## CI / GitHub PR Integration

Status: Not started. Blocked on: real user demand (see criteria below).

What it would involve:
- SARIF 2.1.0 output format (`--format=sarif` flag), mapping findings (mutation survivors, secrets, control-flow issues) to exact file/line positions so GitHub Actions can post them as inline PR comments via code-scanning.
- A separate companion repo, `deployproof-action`, wrapping `deployproof check` for GitHub Actions - kept separate from the core deployproof package rather than bundled into it (same pattern as core mutation-testing tools that ship a thin CI wrapper as a distinct package).

Why not now: No external user has asked for CI integration yet. Building it now would be guessing at requirements instead of building from real demand.

Build trigger: The first time a real user (not the author) asks for CI/PR integration, or the first time deployproof has genuine external adoption and CI integration becomes a natural next ask.

---

## License Decision (Resolved)
Confirmed via research: MIT stays. AGPL was briefly considered earlier for anti-cloning protection, but research confirmed AGPL is subject to explicit, documented bans at Google, is classified "Category X" (banned) by the Apache Software Foundation and FINOS, and is auto-rejected by common enterprise dependency-scanning tools (Sonatype, Aikido). Real precedent: ownCloud and Dgraph both abandoned AGPL specifically due to this exact blocker. MIT remains correct - it's pre-approved and passes automated compliance checks at virtually all large organizations. No action needed - this is confirmation of the existing choice, not a change.

---

## Bus-Factor / Governance (Stage 5, unchanged trigger)
Confirmed via research: OpenSSF Scorecard automatically penalizes solo-maintainer projects on three specific checks (Maintained, Contributors, Code-Review), and these scores feed real automated procurement blocks at large companies. Mitigation options, in order of commitment required: (1) list a designated backup maintainer, (2) pursue foundation/fiscal hosting (PSF, Software Freedom Conservancy), (3) an enterprise retainer model (precedent: Filippo Valsorda / Go cryptography). None of these are worth pursuing until there's real inbound enterprise interest - trigger unchanged from existing Stage 5 entry.
