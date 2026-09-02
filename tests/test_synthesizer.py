"""Unit and integration tests for Automated Test Synthesis ("Self-Healing Tests")."""
import ast
from pathlib import Path
import pytest

from deployproof.mutator import Mutant, MutationResult
from deployproof.synthesizer import (
    FunctionContextLocator,
    SynthesizedTest,
    resolve_import_path,
    synthesize_tests_for_surviving_mutants,
)
from deployproof.reporter import format_report, format_json_report


def test_function_context_locator(tmp_path: Path):
    """Verify FunctionContextLocator correctly pinpoints function AST and argument metadata."""
    code = """class UserManager:
    def validate_age(self, age: int, min_age: int = 18) -> bool:
        if age < min_age:
            return False
        return True
"""
    tree = ast.parse(code)
    locator = FunctionContextLocator(target_line=3)
    locator.visit(tree)

    assert locator.found_function is not None
    assert locator.found_function.name == "validate_age"
    assert locator.enclosing_class == "UserManager"


def test_resolve_import_path():
    """Verify resolve_import_path converts filesystem paths to Python module import paths."""
    root = Path("/workspace/myrepo")
    src_file = root / "src" / "pkg" / "services" / "auth.py"
    assert resolve_import_path(src_file, root) == "pkg.services.auth"

    flat_file = root / "lib" / "utils.py"
    assert resolve_import_path(flat_file, root) == "lib.utils"


def test_synthesize_relational_boundary_test(tmp_path: Path):
    """Verify relational operator mutants trigger boundary inversion tests."""
    sample = tmp_path / "calc.py"
    sample.write_text(
        "def check_limit(val: int, limit: int = 100) -> bool:\n"
        "    if val >= limit:\n"
        "        return True\n"
        "    return False\n",
        encoding="utf-8",
    )

    mutant = Mutant(
        mutant_id="calc.py:2:mut_1",
        file_path=sample,
        line_number=2,
        description="Replace comparison '>=' with '<'",
        original_line="if val >= limit:",
        mutated_line="if val < limit:",
        mutated_source="",
        status="SURVIVED",
    )

    tests = synthesize_tests_for_surviving_mutants([mutant], repo_root=tmp_path)
    assert len(tests) == 1
    t = tests[0]
    assert t.function_name == "check_limit"
    assert t.strategy == "Relational Boundary Value Inversion"
    assert "def test_kill_check_limit_line_2():" in t.test_code
    # Must be valid Python syntax
    ast.parse(t.test_code)


def test_synthesize_dict_fallback_test(tmp_path: Path):
    """Verify dictionary .get() fallback mutant triggers missing-key assertion."""
    sample = tmp_path / "config.py"
    sample.write_text(
        "def get_setting(options: dict, default_val: str = 'auto') -> str:\n"
        "    mode = options.get('mode', default_val)\n"
        "    return mode\n",
        encoding="utf-8",
    )

    mutant = Mutant(
        mutant_id="config.py:2:mut_2",
        file_path=sample,
        line_number=2,
        description="Remove dictionary .get() default fallback (replace with None)",
        original_line="mode = options.get('mode', default_val)",
        mutated_line="mode = options.get('mode', None)",
        mutated_source="",
        status="SURVIVED",
    )

    tests = synthesize_tests_for_surviving_mutants([mutant], repo_root=tmp_path)
    assert len(tests) == 1
    t = tests[0]
    assert t.strategy == "Missing Key Fallback Assertion"
    assert "def test_kill_get_setting_line_2():" in t.test_code
    ast.parse(t.test_code)


def test_synthesize_string_swap_test(tmp_path: Path):
    """Verify string method swaps trigger asymmetric string token tests."""
    sample = tmp_path / "parser.py"
    sample.write_text(
        "def parse_header(token: str) -> bool:\n"
        "    if token.startswith('Bearer '):\n"
        "        return True\n"
        "    return False\n",
        encoding="utf-8",
    )

    mutant = Mutant(
        mutant_id="parser.py:2:mut_3",
        file_path=sample,
        line_number=2,
        description="Swap string method 'startswith' with 'endswith'",
        original_line="if token.startswith('Bearer '):",
        mutated_line="if token.endswith('Bearer '):",
        mutated_source="",
        status="SURVIVED",
    )

    tests = synthesize_tests_for_surviving_mutants([mutant], repo_root=tmp_path)
    assert len(tests) == 1
    t = tests[0]
    assert t.strategy == "Asymmetric String Token Verification"
    ast.parse(t.test_code)


def test_reporter_renders_synthesized_tests(tmp_path: Path):
    """Verify format_report and format_json_report include synthesized test code."""
    sample = tmp_path / "service.py"
    sample.write_text(
        "def verify_access(roles: list, user: str) -> bool:\n"
        "    if 'admin' in roles:\n"
        "        return True\n"
        "    return False\n",
        encoding="utf-8",
    )

    mutant = Mutant(
        mutant_id="service.py:2:mut_4",
        file_path=sample,
        line_number=2,
        description="Replace comparison 'in' with 'not in'",
        original_line="if 'admin' in roles:",
        mutated_line="if 'admin' not in roles:",
        mutated_source="",
        status="SURVIVED",
    )

    res = MutationResult(
        total_mutants=1,
        killed_mutants=0,
        survived_mutants=[mutant],
        untested_files=[],
        runner_errors=[],
        skipped_constructs=[],
        mutation_score=0.0,
        duration_seconds=0.5,
        files_tested=[sample],
    )

    terminal_out = format_report(res, [sample], repo_root=tmp_path)
    assert "Suggested Pytest Test to Kill Mutant:" in terminal_out
    assert "def test_kill_verify_access_line_2():" in terminal_out

    json_str = format_json_report(res, [sample], repo_root=tmp_path)
    assert "synthesized_tests" in json_str
    assert "test_kill_verify_access_line_2" in json_str


def test_cli_generate_tests_option(tmp_path: Path, monkeypatch):
    """Verify deployproof check --generate-tests writes self-healing tests to disk."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    target_py = src_dir / "math_ops.py"
    target_py.write_text(
        "def compute(a: int, b: int = 10) -> int:\n"
        "    if a > 0:\n"
        "        return a + b\n"
        "    return 0\n",
        encoding="utf-8",
    )

    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    base_test = test_dir / "test_math.py"
    base_test.write_text(
        "from src.math_ops import compute\n"
        "def test_compute_negative():\n"
        "    assert compute(-5) == 0\n",
        encoding="utf-8",
    )

    out_test_file = test_dir / "test_healed.py"

    from deployproof.cli import main
    monkeypatch.chdir(tmp_path)
    # Run with --generate-tests and targeting target_py
    res_code = main(["check", "--files", str(target_py), "--generate-tests", str(out_test_file)])

    assert out_test_file.is_file()
    healed_code = out_test_file.read_text(encoding="utf-8")
    assert "Auto-generated unit tests synthesized by DeployProof" in healed_code
    assert "def test_kill_compute_" in healed_code
    ast.parse(healed_code)


def test_synthesize_class_method_and_async(tmp_path: Path):
    """Verify synthesizer handles class methods, properties, and async functions cleanly."""
    sample = tmp_path / "models.py"
    sample.write_text(
        "class Order:\n"
        "    def __init__(self, amount: float = 0.0):\n"
        "        self.amount = amount\n"
        "    async def process_payment(self, card: str, *, retry: bool = True) -> bool:\n"
        "        if len(card) < 16:\n"
        "            return False\n"
        "        return True\n",
        encoding="utf-8",
    )

    mutant = Mutant(
        mutant_id="models.py:5:mut_async",
        file_path=sample,
        line_number=5,
        description="Replace comparison '<' with '<='",
        original_line="if len(card) < 16:",
        mutated_line="if len(card) <= 16:",
        mutated_source="",
        status="SURVIVED",
    )

    tests = synthesize_tests_for_surviving_mutants([mutant], repo_root=tmp_path)
    assert len(tests) == 1
    t = tests[0]
    assert "@pytest.mark.asyncio" in t.test_code
    assert "async def test_kill_process_payment_line_5():" in t.test_code
    assert "from models import Order" in t.test_code
    assert "obj = Order()" in t.test_code
    assert "await obj.process_payment(" in t.test_code
    ast.parse(t.test_code)
