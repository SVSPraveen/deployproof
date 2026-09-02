import os
import sys
import subprocess
import tempfile
from pathlib import Path
import pytest

from deployproof.mutator import (
    generate_schemata_for_file,
    generate_mutants_for_file,
    run_mutation_tests_parallel,
    _run_mutation_tests_sequential,
)


def test_generate_schemata_basic_arithmetic(tmp_path: Path):
    calc_py = tmp_path / "calc.py"
    calc_py.write_text(
        """def add_positive(a: int, b: int) -> int:
    if a > 0:
        return a + b
    return 0
""",
        encoding="utf-8",
    )

    schemata_source, mutants, switch_map = generate_schemata_for_file(calc_py)
    assert schemata_source is not None
    assert "_dp_m" in schemata_source
    assert len(mutants) > 0
    assert len(switch_map) == len(mutants)

    # Test baseline behavior (no mutant active)
    test_py = tmp_path / "test_calc.py"
    test_py.write_text(
        """from calc import add_positive
def test_add():
    assert add_positive(5, 3) == 8
    assert add_positive(-1, 3) == 0
""",
        encoding="utf-8",
    )

    calc_py.write_text(schemata_source, encoding="utf-8")

    # Baseline pass
    r0 = subprocess.run([sys.executable, "-m", "pytest", "-q", "test_calc.py"], cwd=tmp_path, capture_output=True, text=True)
    assert r0.returncode == 0

    # Activating any mutant that flips '+' to '-' or '>' to '<=' should fail test
    for mid in switch_map.values():
        env = os.environ.copy()
        env["__DEPLOYPROOF_MUTANT__"] = str(mid)
        r_mut = subprocess.run([sys.executable, "-m", "pytest", "-q", "test_calc.py"], cwd=tmp_path, env=env, capture_output=True, text=True)
        # At least one mutant should be killed
        if r_mut.returncode != 0:
            break
    else:
        pytest.fail("Expected at least one schemata mutant to be killed by the test suite")


def test_schemata_parallel_execution(tmp_path: Path):
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    lib_py = src_dir / "lib.py"
    lib_py.write_text(
        """def check_discount(price: float, is_vip: bool) -> float:
    if is_vip and price > 100:
        return price * 0.8
    return price
""",
        encoding="utf-8",
    )

    test_dir = tmp_path / "tests"
    test_dir.mkdir(parents=True)
    test_lib = test_dir / "test_lib.py"
    test_lib.write_text(
        """from src.lib import check_discount
def test_discount():
    assert check_discount(150, True) == 120.0
    assert check_discount(50, True) == 50
    assert check_discount(150, False) == 150
""",
        encoding="utf-8",
    )

    res = run_mutation_tests_parallel(
        target_files=[lib_py],
        repo_root=tmp_path,
        workers=2,
        is_full_repo=True,
        quiet=True,
    )

    assert res.total_mutants > 0
    assert res.killed_mutants > 0
    assert res.mutation_score is not None
    assert res.mutation_score > 0.0


def test_schemata_sequential_execution(tmp_path: Path):
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    lib_py = src_dir / "math_ops.py"
    lib_py.write_text(
        """def multiply(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return a * b
""",
        encoding="utf-8",
    )

    test_dir = tmp_path / "tests"
    test_dir.mkdir(parents=True)
    test_lib = test_dir / "test_math_ops.py"
    test_lib.write_text(
        """from src.math_ops import multiply
def test_multiply():
    assert multiply(3, 4) == 12
    assert multiply(0, 5) == 0
    assert multiply(5, 0) == 0
""",
        encoding="utf-8",
    )

    res = _run_mutation_tests_sequential(
        target_files=[lib_py],
        repo_root=tmp_path,
        is_full_repo=True,
        quiet=True,
    )

    assert res.total_mutants > 0
    assert res.killed_mutants > 0
    assert res.mutation_score is not None
    assert res.mutation_score >= 50.0


def test_schemata_mutated_line_accuracy(tmp_path: Path):
    """Verify that every generated mutant has a distinct, accurate mutated_line != original_line."""
    code_file = tmp_path / "sample.py"
    code_file.write_text(
        "def compute(x: float) -> float:\n"
        "    if x > 10:\n"
        "        return x * 2\n"
        "    return 0.0\n",
        encoding="utf-8",
    )

    _, mutants, _ = generate_schemata_for_file(code_file)
    assert len(mutants) >= 3

    # Check that mutated_line is never identical to original_line
    for m in mutants:
        assert m.original_line != "", f"Original line should not be empty for {m.mutant_id}"
        assert m.mutated_line != m.original_line, (
            f"Mutated line should differ from original for {m.description}. "
            f"Got Orig='{m.original_line}', Mut='{m.mutated_line}'"
        )

    # Check specific mutations
    op_mutants = [m for m in mutants if "operator '*'" in m.description]
    assert len(op_mutants) >= 1
    assert "return x / 2" in op_mutants[0].mutated_line

    ret_mutants = [m for m in mutants if "return value with None" in m.description]
    assert len(ret_mutants) >= 1
    assert any(m.mutated_line == "return None" for m in ret_mutants)

