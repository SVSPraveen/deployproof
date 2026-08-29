"""Regression tests for baseline test suite collection and startup failures."""

import json
import tempfile
from pathlib import Path

from deployproof.cli import main
from deployproof.mutator import MutationResult, run_mutation_tests
from deployproof.reporter import format_json_report, format_report


def test_baseline_import_error_detected_without_mutation_score():
    """
    Verify that when the test suite has an ImportError / ModuleNotFoundError at baseline:
    - No mutants are generated/tested
    - mutation_score is None (no fake 0.0%)
    - collection_error is populated with the underlying module name
    - CLI returns exit code 2
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        src = root / "calculator.py"
        src.write_text("def multiply(a: int, b: int) -> int:\n    return a * b\n", encoding="utf-8")

        test = root / "test_calc.py"
        test.write_text("import non_existent_dep_pkg_xyz\n\ndef test_multiply():\n    assert True\n", encoding="utf-8")

        res = run_mutation_tests(
            target_files=[src],
            repo_root=root,
            extra_pytest_args=[str(test)],
        )

        assert res.collection_error is not None
        assert "non_existent_dep_pkg_xyz" in res.collection_error
        assert res.mutation_score is None

        # Verify text reporter formatting
        report = format_report(res, target_files=[src], repo_root=root)
        assert "Could not run test suite — tests failed to execute before any mutation testing began" in report
        assert "non_existent_dep_pkg_xyz" in report
        assert "Score:  0.0%" not in report
        assert "Approx Score:      0.0%" not in report

        # Verify JSON report formatting
        json_report = format_json_report(res, target_files=[src], repo_root=root)
        data = json.loads(json_report)
        assert data["status"] == "error"
        assert data["summary"]["mutation_score"] is None
        assert "non_existent_dep_pkg_xyz" in data["summary"]["collection_error"]
        assert data["mutation_testing"]["score"] is None

        # Verify CLI check returns exit code 2
        exit_code = main(["check", "--files", str(src), "--tests", str(test)])
        assert exit_code == 2


def test_baseline_syntax_error_in_test():
    """
    Verify that a syntax error in a test file produces exit code 2 and collection_error.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        src = root / "app.py"
        src.write_text("def run():\n    return True\n", encoding="utf-8")

        test = root / "test_app.py"
        test.write_text("def test_broken(:\n    assert True\n", encoding="utf-8")

        res = run_mutation_tests(
            target_files=[src],
            repo_root=root,
            extra_pytest_args=[str(test)],
        )

        assert res.collection_error is not None
        assert res.mutation_score is None

        exit_code = main(["check", "--files", str(src), "--tests", str(test)])
        assert exit_code == 2


def test_contrast_genuine_zero_score_vs_collection_error():
    """
    Verify the fundamental distinction:
    - Genuine zero score (tests ran and passed, but killed 0 mutants) -> score 0.0%, exit code 1
    - Collection failure (tests could not run at all) -> score None, exit code 2
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        src = root / "utils.py"
        src.write_text("def check(x: int) -> bool:\n    if x > 10:\n        return True\n    return False\n", encoding="utf-8")

        # 1. Genuine test run that tests nothing in utils.py
        unrelated_test = root / "test_unrelated.py"
        unrelated_test.write_text("def test_always_true():\n    assert 1 == 1\n", encoding="utf-8")

        res_zero = run_mutation_tests(
            target_files=[src],
            repo_root=root,
            extra_pytest_args=[str(unrelated_test)],
        )
        assert res_zero.collection_error is None
        assert res_zero.mutation_score == 0.0
        exit_code_zero = main(["check", "--files", str(src), "--tests", str(unrelated_test)])
        assert exit_code_zero == 1

        # 2. Broken test that fails collection
        broken_test = root / "test_broken.py"
        broken_test.write_text("import completely_missing_library_12345\n", encoding="utf-8")

        res_broken = run_mutation_tests(
            target_files=[src],
            repo_root=root,
            extra_pytest_args=[str(broken_test)],
        )
        assert res_broken.collection_error is not None
        assert res_broken.mutation_score is None
        exit_code_broken = main(["check", "--files", str(src), "--tests", str(broken_test)])
        assert exit_code_broken == 2
