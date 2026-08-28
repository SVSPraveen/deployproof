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
