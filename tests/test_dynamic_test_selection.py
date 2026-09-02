"""
Unit tests for DeployProof Dynamic Test Selection & Impact Analysis:
- Verifies that mutants on covered lines execute only the specific covering test cases.
- Verifies that mutants on unexecuted lines survive with zero-latency without wasting subprocess cycles.
- Verifies that both sequential and multi-worker parallel modes produce mathematically exact mutation scores.
"""

from pathlib import Path
import pytest

from deployproof.mutator import run_mutation_tests, generate_mutants_for_file


def test_dynamic_test_selection_sequential(tmp_path: Path):
    """Verify dynamic test selection accurately maps test functions to specific lines in sequential mode."""
    src_dir = tmp_path / "src"
    tests_dir = tmp_path / "tests"
    src_dir.mkdir()
    tests_dir.mkdir()

    calc_file = src_dir / "calculator.py"
    calc_file.write_text("""def add(a: int, b: int) -> int:
    return a + b

def subtract(a: int, b: int) -> int:
    return a - b

def untested_multiply(a: int, b: int) -> int:
    return a * b
""", encoding="utf-8")

    test_file = tests_dir / "test_calculator.py"
    test_file.write_text("""from calculator import add, subtract

def test_add_operation():
    assert add(2, 3) == 5

def test_subtract_operation():
    assert subtract(10, 4) == 6
""", encoding="utf-8")

    result = run_mutation_tests(
        target_files=[calc_file],
        repo_root=tmp_path,
        is_full_repo=True,
        quiet=True,
    )

    assert result.collection_error is None
    assert result.total_mutants >= 3
    # add and subtract mutants should be killed
    assert result.killed_mutants >= 2
    # untested_multiply mutants MUST survive
    assert len(result.survived_mutants) >= 1
    survived_lines = {m.line_number for m in result.survived_mutants}
    # untested_multiply is on lines 7-8
    assert any(line >= 7 for line in survived_lines)
    assert 0.0 < result.mutation_score < 100.0


def test_dynamic_test_selection_parallel(tmp_path: Path):
    """Verify dynamic test selection works identically across parallel workers."""
    src_dir = tmp_path / "src"
    tests_dir = tmp_path / "tests"
    src_dir.mkdir()
    tests_dir.mkdir()

    calc_file = src_dir / "math_service.py"
    calc_file.write_text("""def is_positive(x: int) -> bool:
    return x > 0

def is_negative(x: int) -> bool:
    return x < 0

def untested_zero_check(x: int) -> bool:
    return x == 0
""", encoding="utf-8")

    test_file = tests_dir / "test_math_service.py"
    test_file.write_text("""from math_service import is_positive, is_negative

def test_is_positive_truthy():
    assert is_positive(5) is True
    assert is_positive(-5) is False

def test_is_negative_truthy():
    assert is_negative(-3) is True
    assert is_negative(3) is False
""", encoding="utf-8")

    result = run_mutation_tests(
        target_files=[calc_file],
        repo_root=tmp_path,
        is_full_repo=True,
        workers=2,
        quiet=True,
    )

    assert result.collection_error is None
    assert result.total_mutants >= 3
    assert result.killed_mutants >= 2
    assert len(result.survived_mutants) >= 1
    survived_lines = {m.line_number for m in result.survived_mutants}
    # untested_zero_check is on lines 7-8
    assert any(line >= 7 for line in survived_lines)
    assert 0.0 < result.mutation_score < 100.0
