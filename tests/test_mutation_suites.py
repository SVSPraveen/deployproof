"""Tests verifying DeployProof mutation scoring with weak and thorough test suites."""

import tempfile
from pathlib import Path
from deployproof.mutator import run_mutation_tests


def test_weak_test_suite_shows_survivors():
    """
    Verify that a deliberately weak test suite fails to kill all mutants,
    resulting in surviving mutants and a score < 100%.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        
        # Source module under test
        src_file = root / "pricing.py"
        src_file.write_text(
            "def is_eligible_discount(age: int, is_student: bool) -> bool:\n"
            "    if is_student and age < 25:\n"
            "        return True\n"
            "    if age >= 65:\n"
            "        return True\n"
            "    return False\n",
            encoding="utf-8",
        )

        # Weak test: only tests a single positive case, missing all edge cases
        test_file = root / "test_pricing.py"
        test_file.write_text(
            "from pricing import is_eligible_discount\n\n"
            "def test_simple_student():\n"
            "    # Line coverage is partial, boundary conditions not tested\n"
            "    assert is_eligible_discount(20, True) is True\n",
            encoding="utf-8",
        )

        result = run_mutation_tests(
            target_files=[src_file],
            repo_root=root,
            extra_pytest_args=[str(test_file)],
        )

        assert result.total_mutants > 0
        assert len(result.survived_mutants) > 0, "Weak test suite must allow mutants to survive"
        assert result.mutation_score < 100.0, f"Expected score < 100%, got {result.mutation_score}%"

        # Verify surviving mutant metadata
        survivor = result.survived_mutants[0]
        assert survivor.file_path == src_file
        assert survivor.line_number > 0
        assert survivor.description != ""
        assert survivor.status == "SURVIVED"


def test_thorough_test_suite_kills_all_mutants():
    """
    Verify that a comprehensive test suite kills all mutants,
    achieving 100% mutation score.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()

        # Source module under test
        src_file = root / "math_utils.py"
        src_file.write_text(
            "def max_of_two(a: int, b: int) -> int:\n"
            "    if a > b:\n"
            "        return a\n"
            "    return b\n",
            encoding="utf-8",
        )

        # Thorough test suite covering all branches and boundary conditions
        test_file = root / "test_math_utils.py"
        test_file.write_text(
            "from math_utils import max_of_two\n\n"
            "def test_max_first_greater():\n"
            "    assert max_of_two(10, 5) == 10\n\n"
            "def test_max_second_greater():\n"
            "    assert max_of_two(3, 8) == 8\n\n"
            "def test_max_equal():\n"
            "    assert max_of_two(4, 4) == 4\n",
            encoding="utf-8",
        )

        result = run_mutation_tests(
            target_files=[src_file],
            repo_root=root,
            extra_pytest_args=[str(test_file)],
        )

        assert result.total_mutants > 0
        assert len(result.survived_mutants) == 0, "Thorough test suite should kill all mutants"
        assert result.mutation_score == 100.0, f"Expected 100%, got {result.mutation_score}%"
        assert result.killed_mutants == result.total_mutants
