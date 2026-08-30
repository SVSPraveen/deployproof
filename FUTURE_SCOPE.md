# DeployProof — Future Scope Backlog

This is a running list of features that are explicitly NOT being built now — captured so they aren't lost, not because they're scheduled.

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
