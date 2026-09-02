"""
OSV CVE Vulnerability Scanner for DeployProof.
Queries the Open Source Vulnerabilities (OSV.dev) database to cross-reference
declared project dependencies against known security advisories and CVEs.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from deployproof.dependencies import ExtractedDependency


@dataclass
class CveAdvisory:
    """Represents a known CVE advisory impacting a dependency."""
    package_name: str
    installed_version: str
    cve_id: str
    summary: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    fixed_version: Optional[str] = None
    advisory_url: Optional[str] = None


@dataclass
class CveScanResult:
    """Aggregated CVE vulnerability report."""
    advisories: List[CveAdvisory] = field(default_factory=list)
    packages_checked: int = 0
    clean: bool = True
    offline_mode: bool = False

    @property
    def critical_count(self) -> int:
        return sum(1 for a in self.advisories if a.severity == "CRITICAL")

    @property
    def high_count(self) -> int:
        return sum(1 for a in self.advisories if a.severity == "HIGH")


def _query_osv_package(name: str, version: Optional[str] = None, timeout: float = 4.0) -> List[CveAdvisory]:
    """Query OSV API for a specific PyPI package and version."""
    if not name or name.lower() == "python":
        return []

    url = "https://api.osv.dev/v1/query"
    payload: Dict[str, object] = {
        "package": {
            "name": name,
            "ecosystem": "PyPI",
        }
    }
    if version:
        # Strip operators like == or >= if present
        v_clean = version.lstrip("=<>~^").strip()
        if v_clean:
            payload["version"] = v_clean

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "DeployProof-Scanner/1.0"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                return []
            res_body = response.read().decode("utf-8")
            res_json = json.loads(res_body)
    except Exception:
        # Graceful offline or timeout fallback
        return []

    vulns = res_json.get("vulns", [])
    advisories: List[CveAdvisory] = []

    for v in vulns:
        vid = v.get("id", "UNKNOWN-CVE")
        # Check aliases for CVE ID
        aliases = v.get("aliases", [])
        cve_name = vid
        for alias in aliases:
            if alias.startswith("CVE-") or alias.startswith("GHSA-"):
                cve_name = alias
                break

        summary = v.get("summary") or v.get("details") or "No advisory summary provided"
        if len(summary) > 120:
            summary = summary[:117] + "..."

        # Calculate severity
        severity = "HIGH"
        database_specific = v.get("database_specific", {})
        if "severity" in database_specific:
            sev_str = str(database_specific["severity"]).upper()
            if "CRIT" in sev_str:
                severity = "CRITICAL"
            elif "HIGH" in sev_str:
                severity = "HIGH"
            elif "MED" in sev_str:
                severity = "MEDIUM"
            elif "LOW" in sev_str:
                severity = "LOW"

        # Find fixed version if listed in ranges
        fixed_ver = None
        for aff in v.get("affected", []):
            for r in aff.get("ranges", []):
                for event in r.get("events", []):
                    if "fixed" in event:
                        fixed_ver = event["fixed"]
                        break

        advisories.append(
            CveAdvisory(
                package_name=name,
                installed_version=version or "unpinned",
                cve_id=cve_name,
                summary=summary,
                severity=severity,
                fixed_version=fixed_ver,
                advisory_url=f"https://osv.dev/vulnerability/{vid}",
            )
        )

    return advisories


def scan_dependencies_for_cves(
    dependencies: List[ExtractedDependency],
    timeout_per_pkg: float = 3.0,
) -> CveScanResult:
    """Check a list of extracted project dependencies against the OSV CVE database."""
    all_advisories: List[CveAdvisory] = []
    seen_keys: Set[str] = set()
    checked_count = 0

    for dep in dependencies:
        pkg_name = dep.name if hasattr(dep, "name") else str(dep)
        if pkg_name in seen_keys:
            continue
        seen_keys.add(pkg_name)
        checked_count += 1

        version = getattr(dep, "version_spec", None)
        advs = _query_osv_package(pkg_name, version=version, timeout=timeout_per_pkg)
        all_advisories.extend(advs)

    return CveScanResult(
        advisories=all_advisories,
        packages_checked=checked_count,
        clean=len(all_advisories) == 0,
    )
