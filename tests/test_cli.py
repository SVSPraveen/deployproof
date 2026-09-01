"""Tests for DeployProof CLI."""

import tempfile
from pathlib import Path
import pytest
from deployproof import __version__
from deployproof.cli import create_parser, main


def test_version():
    """Verify version string is accessible."""
    assert __version__ == "1.0.0"


def test_parser_version(capsys):
    """Verify --version flag outputs version and exits cleanly."""
    parser = create_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "deployproof 1.0.0" in captured.out or "deployproof 1.0.0" in captured.err


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


def test_main_init(tmp_path: Path, capsys, monkeypatch):
    """Verify main 'init' subcommand creates config file and sets up git pre-push hook."""
    monkeypatch.chdir(tmp_path)
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)

    exit_code = main(["init"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Initializing" in captured.out
    assert "Created configuration file: .deployproof.json" in captured.out
    assert "Installed git pre-push hook" in captured.out

    # Check files exist on disk
    config_file = tmp_path / ".deployproof.json"
    assert config_file.exists()
    assert '"threshold": 80.0' in config_file.read_text(encoding="utf-8")

    hook_file = tmp_path / ".git" / "hooks" / "pre-push"
    assert hook_file.exists()
    assert "deployproof check" in hook_file.read_text(encoding="utf-8")

    # Second run should be idempotent
    exit_code2 = main(["init"])
    assert exit_code2 == 0
    captured2 = capsys.readouterr()
    assert "Configuration file already exists" in captured2.out


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


def test_main_check_json_output_passing(capsys):
    """Verify running check with --json outputs valid, structured JSON and exit code 0."""
    import json

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        src = root / "ops.py"
        src.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
        test = root / "test_ops.py"
        test.write_text("from ops import add\ndef test_add():\n    assert add(1, 2) == 3\n    assert add(-1, 1) == 0\n", encoding="utf-8")

        exit_code = main(["check", "--files", str(src), "--json"])
        assert exit_code == 0
        captured = capsys.readouterr()

        data = json.loads(captured.out)
        assert data["status"] == "passed"
        assert data["version"] == "1.0.0"
        assert data["summary"]["mutation_score"] == 100.0
        assert data["summary"]["secrets_found"] == 0
        assert data["summary"]["symlink_escapes_found"] == 0
        assert data["summary"]["dependency_findings"]["high_risk"] == 0
        assert data["summary"]["mock_usages_found"] == 0
        assert data["secrets"]["clean"] is True
        assert data["symlinks"]["clean"] is True
        assert data["dependencies"]["clean"] is True
        assert data["mocks"]["clean"] is True


def test_main_check_json_output_multi_category_findings(tmp_path: Path, capsys, monkeypatch):
    """
    Verify --json against a repo with findings across all categories:
    - Mutation survivor
    - Secret
    - Dependency risk
    - Mock usage
    Confirm it parses back with json.loads and exit code matches the text version (1).
    """
    import json
    import subprocess
    from unittest.mock import patch

    root = tmp_path
    monkeypatch.chdir(root)
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)

    src = root / "service.py"
    src.write_text(
        "import importlib\n\n"
        "OPENAI_API_KEY = 'sk-proj-abc123xyz123abc123xyz123abc123xyz123abc123xyz123'\n\n"
        "def load_plugin():\n"
        "    return importlib.import_module('hallucinated_fake_package_xyz')\n\n"
        "def calculate(x: int) -> int:\n"
        "    if x > 100:\n"
        "        return x * 2\n"
        "    return x + 1\n",
        encoding="utf-8",
    )

    test = root / "test_service.py"
    test.write_text(
        "from unittest.mock import patch\n"
        "from service import calculate\n\n"
        "def test_calculate_weak():\n"
        "    assert calculate(1) == 2\n\n"
        "@patch('service.calculate', return_value=5)\n"
        "def test_mocked_calc(mock_calc):\n"
        "    assert True\n",
        encoding="utf-8",
    )

    def mock_query(pkg, *args, **kwargs):
        return ("HIGH_RISK", None, None, "Package does NOT exist on PyPI (HTTP 404)")

    with patch("deployproof.dependencies.query_pypi_registry", side_effect=mock_query):
        # 1. Run JSON mode
        exit_code = main(["check", "--files", str(src), str(test), "--json"])
        assert exit_code == 1
        captured = capsys.readouterr()

        # Parse JSON output to verify schema and findings
        data = json.loads(captured.out)
        assert data["status"] == "failed"
        assert data["summary"]["secrets_found"] >= 1
        assert data["summary"]["dependency_findings"]["high_risk"] >= 1
        assert data["summary"]["mock_usages_found"] >= 1

        # Check individual sections
        assert len(data["secrets"]["findings"]) >= 1
        assert data["secrets"]["findings"][0]["rule"] == "OpenAI / Anthropic API Key"

        assert len(data["dependencies"]["findings"]) >= 1
        assert data["dependencies"]["findings"][0]["package"] == "hallucinated_fake_package_xyz"
        assert data["dependencies"]["findings"][0]["status"] == "HIGH_RISK"

        assert len(data["mocks"]["findings"]) >= 1
        assert any(f["mock_type"] == "mock_import" for f in data["mocks"]["findings"])
        assert any(f["mock_type"] == "patch_decorator" for f in data["mocks"]["findings"])

        assert len(data["mutation_testing"]["surviving_mutants"]) >= 1

        # 2. Run Text mode on the same files and confirm exit code matches
        exit_code_text = main(["check", "--files", str(src), str(test)])
        assert exit_code_text == exit_code


def test_main_check_full_repo(tmp_path: Path, capsys, monkeypatch):
    """Verify --full-repo flag scans all repository files even when working tree is clean."""
    monkeypatch.chdir(tmp_path)
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@deployproof.dev"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "DeployProof Test"], cwd=tmp_path, capture_output=True, check=True)

    calc_file = tmp_path / "calc.py"
    calc_file.write_text(
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n",
        encoding="utf-8",
    )

    test_file = tmp_path / "test_calc.py"
    test_file.write_text(
        "from calc import add\n\n"
        "def test_add():\n"
        "    assert add(1, 2) == 3\n"
        "    assert add(0, 0) == 0\n",
        encoding="utf-8",
    )

    # Commit all files so git working tree is clean
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmp_path, capture_output=True, check=True)

    # 1. Run standard check on clean repo without --full-repo
    exit_code_diff = main(["check"])
    assert exit_code_diff == 0
    captured_diff = capsys.readouterr()

    # 2. Run check with --full-repo
    exit_code_full = main(["check", "--full-repo"])
    assert exit_code_full == 0
    captured_full = capsys.readouterr()
    assert "Notice: Full repo scan active" in captured_full.out
    assert "calc.py" in captured_full.out
    assert "100.0%" in captured_full.out
    assert "mutants" in captured_full.out
    assert "elapsed:" in captured_full.out


def test_live_progress_output_in_diff_scoped(tmp_path: Path, capsys, monkeypatch):
    """Verify live periodic progress lines are emitted in diff-scoped runs."""
    monkeypatch.chdir(tmp_path)
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@deployproof.dev"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "DeployProof Test"], cwd=tmp_path, capture_output=True, check=True)

    src = tmp_path / "math_utils.py"
    src.write_text("def compute(x: int) -> int:\n    if x > 10:\n        return x * 2\n    return x + 1\n", encoding="utf-8")
    test = tmp_path / "test_math_utils.py"
    test.write_text("from math_utils import compute\ndef test_compute():\n    assert compute(15) == 30\n    assert compute(5) == 6\n", encoding="utf-8")

    exit_code = main(["check", "--files", str(src)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "mutants" in captured.out
    assert "elapsed:" in captured.out


