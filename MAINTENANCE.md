# Maintenance & Support

DeployProof is an open-source tool focused strictly on deterministic pre-push verification for Python (diff-scoped mutation testing, secrets scanning, dependency verification, symlink escape checks, control-flow anomaly detection, and optional multi-worker full-repo audits).

## Scope Limits & Execution Philosophy
DeployProof prioritizes fast, reproducible, and zero-configuration local developer workflows. The primary daily workflow (`deployproof check`) is scoped strictly to active session diffs for 2–5 second execution speed. Full repository audits (`--full-repo`) scale honestly with codebase size and test suite runtime (from minutes on small libraries to an hour+ on heavy repositories with live network tests).

## Issue Triage Cadence
Issues and pull requests are triaged on a best-effort, periodic cadence (typically weekly). Critical security disclosures and reproducible bug reports against supported environments are prioritized first.

## Issues as Feedback
GitHub Issues are a venue for actionable feedback, bug reports, and discussions — not commercial service requests or guaranteed SLA ticketing. Contributions that include minimal reproducible examples and clean test cases are warmly appreciated.
