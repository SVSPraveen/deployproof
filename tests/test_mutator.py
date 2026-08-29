"""Tests for AST mutant generation and transformer logic."""

import ast
import tempfile
from pathlib import Path
from deployproof.mutator import (
    generate_mutants_for_file,
    MutationCounter,
    MutationTransformer,
)


def test_generate_mutants_operators():
    """Verify mutants generated for comparisons, arithmetic, booleans, and constants."""
    code = """def calc_discount(price, is_member, count):
    discount = 0
    if is_member and price >= 100:
        discount = price * 0.1
    elif count > 5:
        discount = 10
    return price - discount
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "sample.py"
        f.write_text(code, encoding="utf-8")

        mutants = generate_mutants_for_file(f)
        assert len(mutants) >= 6

        descriptions = [m.description for m in mutants]
        assert any("Replace logical operator 'and' with 'or'" in d for d in descriptions)
        assert any("Replace comparison '>=' with '<'" in d for d in descriptions)
        assert any("Replace comparison '>' with '<='" in d for d in descriptions)
        assert any("Replace binary operator '*' with '/'" in d for d in descriptions)
        assert any("Replace binary operator '-' with '+'" in d for d in descriptions)


def test_generate_mutants_empty_file():
    """Verify empty or non-code files produce zero mutants."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "empty.py"
        f.write_text("# Only comments\n", encoding="utf-8")
        mutants = generate_mutants_for_file(f)
        assert mutants == []


def test_generate_mutants_syntax_error():
    """Verify syntax error files are safely handled without crash."""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "bad.py"
        f.write_text("def broken(: syntax error\n", encoding="utf-8")
        mutants = generate_mutants_for_file(f)
        assert mutants == []


def test_log_and_exception_messages_excluded_from_mutation():
    """Verify logging calls, print statements, and exception messages are excluded from mutation."""
    code = """import logging
logger = logging.getLogger(__name__)

def check_access(user_id, role):
    if user_id <= 0:
        logger.error("Invalid user id: %s", user_id)
        print("Warning: unauthorized access attempt for: " + str(user_id))
        raise ValueError("User ID must be positive: " + str(user_id))
    if role == "admin":
        logger.info("Admin granted access")
        return True
    return False
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "auth.py"
        f.write_text(code, encoding="utf-8")

        mutants = generate_mutants_for_file(f)
        descriptions = [m.description for m in mutants]
        lines_mutated = [m.line_number for m in mutants]

        # Lines with logging/print/raise messages should NOT have message mutants
        # Line 6: logger.error(...)
        # Line 7: print(...)
        # Line 8: raise ValueError(...)
        assert 6 not in lines_mutated
        assert 7 not in lines_mutated
        assert 8 not in lines_mutated

        # Line 5 (if user_id <= 0) and Line 9 (if role == "admin") MUST be mutated
        assert 5 in lines_mutated
        assert 9 in lines_mutated


def test_logic_bug_with_log_statement_scenario():
    """
    Verify scenario:
    Source file has both a real logic bug (e.g. rate > 0.5) AND logging/print statements.
    Tests only cover the base case, letting the branch mutant survive.
    Confirm only the logic bug shows as a surviving mutant, not the log string.
    """
    from deployproof.mutator import run_mutation_tests

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        src = root / "discount.py"
        src.write_text(
            "import logging\n"
            "logger = logging.getLogger(__name__)\n\n"
            "def calculate(price: float, rate: float) -> float:\n"
            "    logger.info('Calculating discount for price: %s with rate: %s', price, rate)\n"
            "    print('Debug: rate is ' + str(rate))\n"
            "    if rate > 0.5:\n"
            "        return price * 0.5\n"
            "    return price * (1.0 - rate)\n",
            encoding="utf-8",
        )

        test = root / "test_discount.py"
        # Weak test: only tests standard rate <= 0.5, misses the rate > 0.5 branch
        test.write_text(
            "from discount import calculate\n\n"
            "def test_calculate():\n"
            "    assert calculate(100.0, 0.2) == 80.0\n",
            encoding="utf-8",
        )

        result = run_mutation_tests(
            target_files=[src],
            repo_root=root,
            extra_pytest_args=[str(test)],
        )

        # Confirm surviving mutants exist for logic, but none for log or print lines (lines 5 and 6)
        assert len(result.survived_mutants) > 0
        survived_lines = [m.line_number for m in result.survived_mutants]
        assert 5 not in survived_lines  # logger.info
        assert 6 not in survived_lines  # print
        assert 7 in survived_lines or 8 in survived_lines  # logic bug


def test_mutant_snippet_display_preserves_variable_names():
    """Verify that mutating a numeric constant does not corrupt variable names containing digits."""
    code = "is_py3 = _ver[0] == 3\n"
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "compat.py"
        f.write_text(code, encoding="utf-8")

        mutants = generate_mutants_for_file(f)
        const_3_mutants = [m for m in mutants if "Replace numeric constant '3' with '4'" in m.description]
        assert len(const_3_mutants) == 1
        m = const_3_mutants[0]
        assert m.original_line == "is_py3 = _ver[0] == 3"
        assert m.mutated_line == "is_py3 = _ver[0] == 4"
        assert "is_py4" not in m.mutated_line


