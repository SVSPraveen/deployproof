import json
import subprocess
from pathlib import Path
import pytest

from deployproof.cli import create_parser, handle_check, load_repo_config


def test_load_repo_config_reads_json(tmp_path):
    config_file = tmp_path / ".deployproof.json"
    config_file.write_text(
        json.dumps({
            "threshold": 5.0,
            "timeout": 25.0,
            "strict_mocks": True,
            "secrets_scanning": False,
        }),
        encoding="utf-8",
    )

    cfg = load_repo_config(tmp_path)
    assert cfg["threshold"] == 5.0
    assert cfg["timeout"] == 25.0
    assert cfg["strict_mocks"] is True
    assert cfg["secrets_scanning"] is False


def test_cli_honors_config_threshold_and_flags(tmp_path, monkeypatch):
    """Bug #5: Verify deployproof check reads .deployproof.json and applies threshold."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)

    config_file = repo / ".deployproof.json"
    config_file.write_text(
        json.dumps({
            "threshold": 5.0,
            "timeout": 3.0,
        }),
        encoding="utf-8",
    )

    app_py = repo / "app.py"
    app_py.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    test_py = repo / "test_app.py"
    test_py.write_text("def test_dummy():\n    pass\n", encoding="utf-8")

    monkeypatch.chdir(repo)

    parser = create_parser()
    args = parser.parse_args(["check", "--json"])
    
    # Run check
    import io
    import sys
    stdout_buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout_buf)

    code = handle_check(args)
    output = stdout_buf.getvalue()
    data = json.loads(output)
    
    # Verify threshold in report matches .deployproof.json (5.0, not default 80.0)
    assert data["summary"]["threshold"] == 5.0
