# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.1.x   | :white_check_mark: |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

---

## Reporting a Vulnerability

DeployProof is dedicated to local-first security and developer safety. If you discover a security vulnerability, sandbox-escape defect, or potential credential exposure vector within DeployProof:

1. **Do NOT open a public GitHub issue.**
2. Please report findings privately via **GitHub Private Vulnerability Reporting** on the repository page: `https://github.com/SVSPraveen/deployproof/security/advisories/new`.
3. Include a detailed description of the vulnerability, reproduction steps or sample repository fixture, and potential impact.

### Response & Disclosure Process

* **Acknowledgment**: You will receive an initial response confirming receipt of your report within 48 hours.
* **Assessment & Fix**: A triage assessment and patch timeline will be shared following verification.
* **Coordinated Disclosure**: A public advisory and CVE (if applicable) will be published alongside the patched release on PyPI.

---

## Security Guarantees & Scope

* **Local-First Processing**: DeployProof runs strictly on the local machine with zero external telemetry.
* **Network Boundaries**: Outbound HTTP requests are strictly limited to the official PyPI JSON API (`https://pypi.org/pypi/<pkg>/json`) for package existence and registration timestamp verification.
* **Sandbox Isolation**: Temporary process sandboxes created during parallel mutation testing (`--workers`) are automatically cleaned up on process termination via signal handlers.
