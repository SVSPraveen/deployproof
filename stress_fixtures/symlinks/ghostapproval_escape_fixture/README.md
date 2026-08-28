# GhostApproval Sandbox-Escape Symlink Stress Fixture (CVE-2026-50549 / CWE-61 / CWE-451)

This fixture demonstrates a GhostApproval-class sandbox-escape vulnerability:
- Apparent path shown to developer: `config/app_settings.json`
- Resolved target: `../../../../etc/shadow` (or external host sensitive directory)

DeployProof intercepts this during session diff scanning, verifies the path escape, and blocks execution without silently opening or leaking target file contents.
