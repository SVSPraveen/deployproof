"""Unit and integration tests for Interactive Quick-Fix mode."""
import ast
import io
from pathlib import Path
import pytest

from deployproof.interactive import prompt_apply_synthesized_tests
from deployproof.mutator import Mutant


def test_interactive_non_tty_skips_cleanly(tmp_path: Path, monkeypatch, capsys):
    """Verify interactive mode does not block or prompt when running in non-interactive (non-TTY) shells."""
    sample_py = tmp_path / "calc.py"
    sample_py.write_text("def add(a: int, b: int) -> int:\n    if a > 0:\n        return a + b\n    return 0\n", encoding="utf-8")

    mutant = Mutant(
        mutant_id="calc.py:2:mut_1",
        file_path=sample_py,
        line_number=2,
        description="Replace relational operator '>' with '>='",
        original_line="if a > 0:",
        mutated_line="if a >= 0:",
        mutated_source="",
        status="SURVIVED",
    )

    # In standard pytest, sys.stdin.isatty() is False
    applied = prompt_apply_synthesized_tests([mutant], repo_root=tmp_path)
    assert applied == 0
    captured = capsys.readouterr()
    assert "Non-interactive shell detected" in captured.out


def test_interactive_applies_test_on_yes(tmp_path: Path, monkeypatch, capsys):
    """Verify interactive mode appends synthesized test when user enters 'y'."""
    sample_py = tmp_path / "calc.py"
    sample_py.write_text("def add(a: int, b: int) -> int:\n    if a > 0:\n        return a + b\n    return 0\n", encoding="utf-8")

    mutant = Mutant(
        mutant_id="calc.py:2:mut_1",
        file_path=sample_py,
        line_number=2,
        description="Replace relational operator '>' with '>='",
        original_line="if a > 0:",
        mutated_line="if a >= 0:",
        mutated_source="",
        status="SURVIVED",
    )

    out_file = tmp_path / "tests" / "test_healed.py"

    # Mock isatty to return True
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    # Mock input to return 'y'
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")

    applied = prompt_apply_synthesized_tests([mutant], repo_root=tmp_path, output_file_override=out_file)
    assert applied == 1
    assert out_file.is_file()
    content = out_file.read_text(encoding="utf-8")
    assert "def test_kill_add_line_2():" in content
    ast.parse(content)


def test_interactive_skips_test_on_no(tmp_path: Path, monkeypatch, capsys):
    """Verify interactive mode skips test when user enters 'n'."""
    sample_py = tmp_path / "calc.py"
    sample_py.write_text("def add(a: int, b: int) -> int:\n    if a > 0:\n        return a + b\n    return 0\n", encoding="utf-8")

    mutant = Mutant(
        mutant_id="calc.py:2:mut_1",
        file_path=sample_py,
        line_number=2,
        description="Replace relational operator '>' with '>='",
        original_line="if a > 0:",
        mutated_line="if a >= 0:",
        mutated_source="",
        status="SURVIVED",
    )

    out_file = tmp_path / "tests" / "test_healed.py"

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")

    applied = prompt_apply_synthesized_tests([mutant], repo_root=tmp_path, output_file_override=out_file)
    assert applied == 0
    assert not out_file.exists()


def test_interactive_applies_all_on_all(tmp_path: Path, monkeypatch, capsys):
    """Verify interactive mode applies all tests without further prompting when user enters 'all'."""
    sample_py = tmp_path / "calc.py"
    sample_py.write_text("def add(a: int, b: int) -> int:\n    if a > 0:\n        return a + b\n    return 0\n", encoding="utf-8")

    mutants = [
        Mutant(
            mutant_id="calc.py:2:mut_1",
            file_path=sample_py,
            line_number=2,
            description="Replace relational operator '>' with '>='",
            original_line="if a > 0:",
            mutated_line="if a >= 0:",
            mutated_source="",
            status="SURVIVED",
        ),
        Mutant(
            mutant_id="calc.py:4:mut_2",
            file_path=sample_py,
            line_number=4,
            description="Replace numeric constant '0' with '1'",
            original_line="return 0",
            mutated_line="return 1",
            mutated_source="",
            status="SURVIVED",
        ),
    ]

    out_file = tmp_path / "tests" / "test_healed.py"

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    # First prompt enters 'all'
    monkeypatch.setattr("builtins.input", lambda prompt="": "all")

    applied = prompt_apply_synthesized_tests(mutants, repo_root=tmp_path, output_file_override=out_file)
    assert applied == 2
    assert out_file.is_file()
    content = out_file.read_text(encoding="utf-8")
    assert "def test_kill_add_line_2():" in content
    assert "def test_kill_add_line_4():" in content
    ast.parse(content)
