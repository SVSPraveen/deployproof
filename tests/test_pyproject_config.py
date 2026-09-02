"""Unit and integration tests for pyproject.toml [tool.deployproof] configuration support."""
import json
from pathlib import Path
import pytest

from deployproof.cli import load_repo_config, main


def test_load_repo_config_from_pyproject_toml(tmp_path: Path):
    """Verify load_repo_config extracts settings from [tool.deployproof] in pyproject.toml."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[tool.deployproof]
threshold = 85.5
timeout = 15.0
workers = 4
strict_mocks = true
strict_error_handling = true
sast_scanning = false
generate_tests = "tests/test_healed.py"
""",
        encoding="utf-8",
    )

    cfg = load_repo_config(tmp_path)
    assert cfg["threshold"] == 85.5
    assert cfg["timeout"] == 15.0
    assert cfg["workers"] == 4
    assert cfg["strict_mocks"] is True
    assert cfg["strict_error_handling"] is True
    assert cfg["sast_scanning"] is False
    assert cfg["generate_tests"] == "tests/test_healed.py"


def test_pyproject_toml_precedence_overridden_by_json(tmp_path: Path):
    """Verify .deployproof.json overrides pyproject.toml [tool.deployproof]."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.deployproof]
threshold = 85.0
timeout = 15.0
""",
        encoding="utf-8",
    )

    json_cfg = tmp_path / ".deployproof.json"
    json_cfg.write_text(
        json.dumps({"threshold": 92.0}),
        encoding="utf-8",
    )

    cfg = load_repo_config(tmp_path)
    # Threshold should come from .deployproof.json (92.0), while timeout comes from pyproject.toml (15.0)
    assert cfg["threshold"] == 92.0
    assert cfg["timeout"] == 15.0


def test_cli_check_uses_pyproject_toml_threshold(tmp_path: Path, monkeypatch, capsys):
    """Verify deployproof check respects threshold from pyproject.toml."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    target_py = src_dir / "maths.py"
    target_py.write_text("def sub(a, b): return a - b\n", encoding="utf-8")

    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    test_py = test_dir / "test_maths.py"
    test_py.write_text("from src.maths import sub\ndef test_sub(): assert sub(5, 3) == 2\n", encoding="utf-8")

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.deployproof]
threshold = 95.0
""",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    # Run with json output to easily verify threshold
    res_code = main(["check", "--files", str(target_py), "--json"])

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["summary"]["threshold"] == 95.0


def test_cli_flag_overrides_pyproject_toml_threshold(tmp_path: Path, monkeypatch, capsys):
    """Verify explicit CLI --threshold overrides pyproject.toml configuration."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    target_py = src_dir / "maths.py"
    target_py.write_text("def sub(a, b): return a - b\n", encoding="utf-8")

    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    test_py = test_dir / "test_maths.py"
    test_py.write_text("from src.maths import sub\ndef test_sub(): assert sub(5, 3) == 2\n", encoding="utf-8")

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.deployproof]
threshold = 95.0
""",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    # Override with --threshold 70.0
    res_code = main(["check", "--files", str(target_py), "--threshold", "70.0", "--json"])

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["summary"]["threshold"] == 70.0
