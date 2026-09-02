"""Unit and integration tests for Equivalent Mutant Detection & Elimination."""
import ast
from pathlib import Path
import pytest

from deployproof.mutator import (
    DeadCodeFinder,
    PrunedEquivalentMutant,
    collect_equivalent_mutants_for_file,
    generate_mutants_for_file,
    generate_schemata_for_file,
    is_algebraic_zero_identity,
    is_range_zero_start,
    run_mutation_tests_parallel,
    _run_mutation_tests_sequential,
)
from deployproof.reporter import format_report, format_json_report


def test_dead_code_finder_detection():
    """Verify DeadCodeFinder marks code after unconditional return/raise/break as dead."""
    code = """def compute(x: int) -> int:
    if x > 10:
        return x * 2
        dead_var = 42
        print("dead code")
    if x < 0:
        raise ValueError("negative")
        dead_after_raise = 99
    return x + 1
"""
    tree = ast.parse(code)
    finder = DeadCodeFinder()
    finder.visit(tree)
    # Lines 4, 5 (after return) and line 8 (after raise) should be dead
    assert 4 in finder.dead_lines
    assert 5 in finder.dead_lines
    assert 8 in finder.dead_lines
    assert 2 not in finder.dead_lines
    assert 9 not in finder.dead_lines


def test_algebraic_and_range_identity_detection():
    """Verify algebraic zero identities and range(0, N) are detected as equivalent."""
    code_zero = ast.parse("res = x + 0")
    binop_add = code_zero.body[0].value
    assert is_algebraic_zero_identity(binop_add) is True

    code_sub = ast.parse("res = x - 0")
    binop_sub = code_sub.body[0].value
    assert is_algebraic_zero_identity(binop_sub) is True

    code_normal = ast.parse("res = x + 5")
    binop_normal = code_normal.body[0].value
    assert is_algebraic_zero_identity(binop_normal) is False

    code_range = ast.parse("for i in range(0, 10): pass")
    call_range = code_range.body[0].iter
    assert is_range_zero_start(call_range) is True

    code_range_nonzero = ast.parse("for i in range(1, 10): pass")
    call_range_nonzero = code_range_nonzero.body[0].iter
    assert is_range_zero_start(call_range_nonzero) is False


def test_collect_equivalent_mutants_for_file(tmp_path: Path):
    """Verify collect_equivalent_mutants_for_file catalogs all equivalent locations."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def process(items, offset):\n"
        "    base = offset + 0\n"
        "    config = items.get('key', None)\n"
        "    for idx in range(0, len(items)):\n"
        "        pass\n"
        "    return base\n"
        "    unreachable = 123\n",
        encoding="utf-8",
    )

    pruned = collect_equivalent_mutants_for_file(sample)
    categories = {p.category for p in pruned}
    assert "Algebraic Identity" in categories
    assert "Defensive Redundancy" in categories
    assert "Redundant Range Boundary" in categories
    assert "Dead Code / Unreachable" in categories
    assert any(p.line_number == 7 for p in pruned if p.category == "Dead Code / Unreachable")


def test_schemata_and_generator_skip_equivalent_mutants(tmp_path: Path):
    """Verify generate_mutants_for_file and generate_schemata_for_file exclude equivalent mutants."""
    sample = tmp_path / "math_mod.py"
    sample.write_text(
        "def compute(a: int) -> int:\n"
        "    val = a + 0\n"
        "    return val * 2\n"
        "    print('dead after return')\n",
        encoding="utf-8",
    )

    # 1. Standard mutant generation
    mutants = generate_mutants_for_file(sample)
    mutant_lines = {m.line_number for m in mutants}
    assert 4 not in mutant_lines  # Dead code line pruned

    # 2. Schemata generation
    code, schemata_mutants, s_map = generate_schemata_for_file(sample)
    schemata_lines = {m.line_number for m in schemata_mutants}
    assert 4 not in schemata_lines


def test_reporter_formatting_with_pruned_equivalent_mutants(tmp_path: Path):
    """Verify terminal summary and JSON report render pruned equivalent mutants cleanly."""
    sample = tmp_path / "service.py"
    sample.write_text("def run(): pass\n", encoding="utf-8")

    from deployproof.mutator import MutationResult

    res = MutationResult(
        total_mutants=10,
        killed_mutants=10,
        survived_mutants=[],
        untested_files=[],
        runner_errors=[],
        skipped_constructs=[],
        pruned_equivalent_mutants=[
            PrunedEquivalentMutant(
                file_path=sample,
                line_number=2,
                category="Defensive Redundancy",
                description="dict.get() None default fallback",
                original_line="d.get('key', None)",
            ),
            PrunedEquivalentMutant(
                file_path=sample,
                line_number=8,
                category="Dead Code / Unreachable",
                description="Code statement placed after unconditional return",
                original_line="print('unreachable')",
            ),
        ],
        mutation_score=100.0,
        duration_seconds=1.2,
        files_tested=[sample],
    )

    # Terminal report check
    terminal_out = format_report(res, [sample])
    assert "Equivalence Pruned (2 unkillable / dead-code mutants omitted from scoring):" in terminal_out
    assert "[Defensive Redundancy]" in terminal_out
    assert "[Dead Code / Unreachable]" in terminal_out

    # JSON report check
    json_str = format_json_report(res, [sample])
    assert "Defensive Redundancy" in json_str
    assert "Dead Code / Unreachable" in json_str
