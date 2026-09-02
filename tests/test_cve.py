"""
Test suite for OSV CVE Vulnerability Scanner.
"""

from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from deployproof.cve import _query_osv_package, scan_dependencies_for_cves, CveScanResult
from deployproof.dependencies import ExtractedDependency


def test_osv_cve_mock_response():
    """Verify parsing of OSV vulnerability payload into structured CveAdvisory objects."""
    mock_payload = b"""{
        "vulns": [
            {
                "id": "GHSA-j87w-593c-2345",
                "aliases": ["CVE-2023-32681"],
                "summary": "Requests vulnerable to leaking Authorization header on redirect",
                "database_specific": {"severity": "HIGH"},
                "affected": [
                    {
                        "ranges": [
                            {
                                "type": "ECOSYSTEM",
                                "events": [{"introduced": "0"}, {"fixed": "2.31.0"}]
                            }
                        ]
                    }
                ]
            }
        ]
    }"""

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = mock_payload
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        advs = _query_osv_package("requests", version="2.28.0")
        assert len(advs) == 1
        adv = advs[0]
        assert adv.cve_id == "CVE-2023-32681"
        assert adv.package_name == "requests"
        assert adv.severity == "HIGH"
        assert adv.fixed_version == "2.31.0"


def test_osv_cve_offline_resilience():
    """Verify graceful fallback without crash when offline or network fails."""
    with patch("urllib.request.urlopen", side_effect=Exception("Network unreachable")):
        dep = ExtractedDependency(name="requests", import_name="requests", source_file=Path("requirements.txt"), lineno=1)
        res = scan_dependencies_for_cves([dep], timeout_per_pkg=0.5)
        assert res.clean is True
        assert len(res.advisories) == 0
