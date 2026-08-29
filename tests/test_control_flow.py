import ast
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from deployproof.cli import main
from deployproof.control_flow import (
    ControlFlowScanner,
    scan_file_for_control_flow,
    scan_session_files_for_control_flow,
)
from deployproof.reporter import format_json_report, format_report
from deployproof.mutator import MutationResult


def test_control_flow_scanner_three_planted_cases(tmp_path: Path):
    """
    Test with three separate planted cases in one file:
    1. A bare except: pass
    2. An except Exception that only logs and swallows
    3. Unreachable code after a return
    Confirm all three are caught individually with correct line numbers.
    """
    src = tmp_path / "sample_bugs.py"
    content = (
        "import logging\n"
        "\n"
        "logger = logging.getLogger(__name__)\n"
        "\n"
        "def bad_bare_handler():\n"
        "    try:\n"
        "        val = 1 / 0\n"
        "    except:\n"              # Line 8: bare_except
        "        pass\n"
        "\n"
        "def bad_swallowed_exception():\n"
        "    try:\n"
        "        val = int('abc')\n"
        "    except Exception as e:\n"  # Line 14: swallowed_exception
        "        logger.error('Failed to parse: %s', e)\n"
        "        print('Swallowing error')\n"
        "\n"
        "def bad_unreachable_code(x: int) -> int:\n"
        "    if x > 0:\n"
        "        return x * 2\n"
        "        print('Unreachable statement 1')\n"  # Line 21: unreachable_code
        "        x = x + 1\n"                         # Line 22: unreachable_code
        "    return 0\n"
    )
    src.write_text(content, encoding="utf-8")

    tree = ast.parse(content)
    scanner = ControlFlowScanner(
        file_path=src,
        source_lines=content.splitlines(),
        modified_lines=None,
    )
    scanner.visit(tree)

    findings = scanner.findings
    assert len(findings) >= 3

    # 1. Bare except finding
    bare_findings = [f for f in findings if f.rule_id == "bare_except"]
    assert len(bare_findings) == 1
    assert bare_findings[0].line_number == 8
    assert "except:" in bare_findings[0].snippet

    # 2. Swallowed exception finding
    swallowed_findings = [f for f in findings if f.rule_id == "swallowed_exception"]
    assert len(swallowed_findings) == 1
    assert swallowed_findings[0].line_number == 14
    assert "except Exception" in swallowed_findings[0].snippet

    # 3. Unreachable code finding
    unreachable_findings = [f for f in findings if f.rule_id == "unreachable_code"]
    assert len(unreachable_findings) >= 1
    assert any(f.line_number == 21 for f in unreachable_findings)


def test_control_flow_scanner_legitimate_cases_not_flagged(tmp_path: Path):
    """
    Confirm legitimate cases are NOT flagged:
    1. A broad except that re-raises after logging
    2. A bare except inside cleanup with a re-raise
    3. An except Exception that returns an error dictionary
    """
    src = tmp_path / "legitimate_handlers.py"
    content = (
        "import logging\n"
        "\n"
        "logger = logging.getLogger(__name__)\n"
        "\n"
        "def cleanup_with_bare_except():\n"
        "    try:\n"
        "        print('acquiring')\n"
        "    except:\n"
        "        print('cleaning up')\n"
        "        raise\n"  # Re-raises: legitimate!
        "\n"
        "def logging_with_reraise():\n"
        "    try:\n"
        "        val = int('abc')\n"
        "    except Exception as e:\n"
        "        logger.error('Log and propagate: %s', e)\n"
        "        raise\n"  # Re-raises: legitimate!
        "\n"
        "def handle_with_error_return():\n"
        "    try:\n"
        "        val = int('xyz')\n"
        "        return {'status': 'ok', 'val': val}\n"
        "    except Exception as e:\n"
        "        logger.warning('Failed: %s', e)\n"
        "        return {'status': 'error', 'error': str(e)}\n"  # Returns error: legitimate!
    )
    src.write_text(content, encoding="utf-8")

    tree = ast.parse(content)
    scanner = ControlFlowScanner(
        file_path=src,
        source_lines=content.splitlines(),
        modified_lines=None,
    )
    scanner.visit(tree)

    # All legitimate cases should produce ZERO findings
    assert len(scanner.findings) == 0


def test_control_flow_diff_scoping(tmp_path: Path):
    """Confirm that findings in unchanged lines are filtered out when diff scoping is active."""
    src = tmp_path / "diff_test.py"
    content = (
        "def old_code():\n"
        "    try:\n"
        "        pass\n"
        "    except:\n"  # Line 4 (unmodified line)
        "        pass\n"
        "\n"
        "def new_code():\n"
        "    return 1\n"
        "    print('new unreachable')\n"  # Line 9 (modified line)
    )
    src.write_text(content, encoding="utf-8")

    tree = ast.parse(content)
    # Only line 9 is modified in diff
    scanner = ControlFlowScanner(
        file_path=src,
        source_lines=content.splitlines(),
        modified_lines={9},
    )
    scanner.visit(tree)

    # Line 4 bare except is skipped because it's not in modified_lines
    assert len(scanner.findings) == 1
    assert scanner.findings[0].line_number == 9
    assert scanner.findings[0].rule_id == "unreachable_code"


def test_cli_strict_error_handling_gate(tmp_path: Path, capsys, monkeypatch):
    """
    Test --strict-error-handling:
    - Exit code is 0 by default (informational)
    - Exit code is 1 when --strict-error-handling is passed
    """
    root = tmp_path
    monkeypatch.chdir(root)
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)

    src = root / "ops.py"
    src.write_text(
        "def calculate(x: int) -> int:\n"
        "    if x > 0:\n"
        "        return x * 2\n"
        "        print('dead code')\n"
        "    return 0\n",
        encoding="utf-8",
    )

    test = root / "test_ops.py"
    test.write_text(
        "from ops import calculate\n\n"
        "def test_calculate():\n"
        "    assert calculate(5) == 10\n"
        "    assert calculate(-1) == 0\n",
        encoding="utf-8",
    )

    # 1. Default run: informational -> exit code 0 (use --threshold 0 to isolate strict-error-handling
    #    gate behaviour from the mutation score gate, since this fixture has minimal test coverage)
    exit_code_default = main(["check", "--files", str(src), str(test), "--threshold", "0"])
    assert exit_code_default == 0
    captured = capsys.readouterr()
    assert "Control Flow & Error Handling (flagged for review):" in captured.out
    assert "unreachable_code" in captured.out

    # 2. Strict run: gate failed -> exit code 1
    exit_code_strict = main(["check", "--files", str(src), str(test), "--threshold", "0", "--strict-error-handling"])
    assert exit_code_strict == 1
    captured_strict = capsys.readouterr()
    assert "[!] STRICT GATE TRIGGERED:" in captured_strict.out
    assert "Pre-check FAILED: 1 control flow / error handling issue(s) detected (--strict-error-handling active)." in captured_strict.out