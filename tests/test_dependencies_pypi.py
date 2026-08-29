"""Tests for PyPI registry check and age analysis (Piece 2)."""

import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
import urllib.error
from deployproof.dependencies import (
    DependencyCheckResult,
    DependencyScanSummary,
    ExtractedDependency,
    query_pypi_registry,
    scan_dependencies,
)


def test_query_pypi_established_package():
    # Live query against requests
    status, age_days, first_date, details = query_pypi_registry("requests", timeout=5.0)
    assert status == "OK"
    assert age_days is not None
    assert age_days > 1000
    assert first_date is not None
    assert "Established package" in details


def test_query_pypi_nonexistent_package():
    # Live query against a guaranteed nonexistent package name
    pkg_name = "deployproof-hallucinated-test-pkg-9999999"
    status, age_days, first_date, details = query_pypi_registry(pkg_name, timeout=5.0)
    assert status == "HIGH_RISK"
    assert age_days is None
    assert "does NOT exist on PyPI" in details


def test_query_pypi_recent_package_mock():
    # Mock PyPI response for package registered 5 days ago
    five_days_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=5)
    iso_time = five_days_ago.isoformat()

    mock_resp_data = {
        "releases": {
            "0.1.0": [{"upload_time_iso_8601": iso_time}]
        }
    }

    import json
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        status, age_days, first_date, details = query_pypi_registry("some-new-pkg", cache={})
        assert status == "MEDIUM_RISK"
        assert age_days == 5
        assert "Recently registered package" in details


def test_query_pypi_network_error_unknown():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        status, age_days, first_date, details = query_pypi_registry("some-pkg", cache={})
        assert status == "UNKNOWN"
        assert "Network / registry connection error" in details


def test_query_pypi_caching():
    cache = {}
    with patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"releases": {"1.0.0": [{"upload_time_iso_8601": "2020-01-01T00:00:00Z"}]}}'
        mock_resp.__enter__.return_value = mock_resp
        mock_url.return_value = mock_resp

        res1 = query_pypi_registry("cached-pkg", cache=cache)
        res2 = query_pypi_registry("cached-pkg", cache=cache)

        # Should only call urlopen once
        assert mock_url.call_count == 1
        assert res1 == res2
        assert res1[0] == "OK"


def test_scan_dependencies_aggregated_summary(tmp_path: Path):
    dummy_file = tmp_path / "app.py"
    dummy_file.write_text("import requests", encoding="utf-8")

    deps = [
        ExtractedDependency("requests", "requests", dummy_file, 1, "import"),
        ExtractedDependency("fake-pkg-12345", "fake-pkg-12345", dummy_file, 2, "import"),
    ]

    with patch("deployproof.dependencies.query_pypi_registry") as mock_query:
        mock_query.side_effect = [
            ("OK", 4000, "2011-02-14", "Established package"),
            ("HIGH_RISK", None, None, "Package does NOT exist on PyPI"),
        ]

        summary = scan_dependencies(deps)
        assert summary.total_scanned == 2
        assert summary.ok_count == 1
        assert summary.high_risk_count == 1
        assert summary.medium_risk_count == 0
        assert summary.unknown_count == 0
        assert len(summary.findings) == 2


def test_namespace_package_backports_ok():
    """Verify namespace packages like backports with 0 direct releases are treated as OK rather than risky."""
    status, age_days, first_date, details = query_pypi_registry("backports", cache={})
    assert status == "OK"
    assert "Namespace package" in details

