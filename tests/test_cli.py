"""Tests for DeployProof CLI."""

import tempfile
from pathlib import Path
import pytest
from deployproof import __version__
from deployproof.cli import create_parser, main


def test_version():
    """Verify version string is defined and matches expected version."""
    assert __version__ == "0.1.0"


def test_parser_version(capsys):
    """Verify --version flag outputs correct version and exits."""
    parser = create_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "deployproof 0.1.0" in captured.out or "deployproof 0.1.0" in captured.err


def test_parser_help(capsys):
    """Verify --help flag outputs help documentation."""
    parser = create_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "deployproof" in captured.out
    assert "deterministic AI-code deployability checker" in captured.out


def test_main_no_args(capsys):
    """Verify main with no arguments displays help and exits with status 0."""
    exit_code = main([])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "deployproof" in captured.out


def test_main_init(capsys):
    """Verify main 'init' subcommand."""
    exit_code = main(["init"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "initialized" in captured.out.lower()


def test_main_check_explicit_files_passing(capsys):
    """Verify running check on a file with thorough tests passes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        src = root / "ops.py"
        src.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
        test = root / "test_ops.py"
        test.write_text("from ops import add\ndef test_add():\n    assert add(1, 2) == 3\n    assert add(-1, 1) == 0\n", encoding="utf-8")

        exit_code = main(["check", "--files", str(src)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "LOCAL PRE-CHECK" in captured.out
        assert "not the verified score" in captured.out
        assert "100.0%" in captured.out
        assert "PASSED" in captured.out
