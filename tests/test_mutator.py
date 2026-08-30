"""Tests for AST mutant generation and transformer logic."""

import ast
import subprocess
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


def test_file_restoration_guarantee_on_interrupt():
    """Verify that original file contents are guaranteed to be restored even if an exception occurs."""
    from deployproof.mutator import run_mutation_tests
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        src = root / "service.py"
        orig_text = "def check(x: int) -> bool:\n    return x > 0\n"
        src.write_text(orig_text, encoding="utf-8")

        test = root / "test_service.py"
        test.write_text("from service import check\ndef test_ok():\n    assert check(1) is True\n", encoding="utf-8")

        # Simulate a KeyboardInterrupt mid-mutation execution
        call_count = 0
        real_run = subprocess.run
        def mock_subprocess_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > 1:  # After baseline, interrupt during mutant run
                raise KeyboardInterrupt("Simulated Ctrl+C")
            return real_run(*args, **kwargs)

        with patch("subprocess.run", side_effect=mock_subprocess_run):
            try:
                run_mutation_tests(
                    target_files=[src],
                    repo_root=root,
                    extra_pytest_args=[str(test)],
                )
            except KeyboardInterrupt:
                pass

        # File MUST be restored to original contents
        assert src.read_text(encoding="utf-8") == orig_text


def test_timeout_mutant_treated_as_killed():
    """Verify that a mutant test run that times out is treated as KILLED and restores the file."""
    from deployproof.mutator import run_mutation_tests
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        src = root / "service.py"
        orig_text = "def check(x: int) -> bool:\n    return x > 0\n"
        src.write_text(orig_text, encoding="utf-8")

        test = root / "test_service.py"
        test.write_text("from service import check\ndef test_ok():\n    assert check(1) is True\n", encoding="utf-8")

        call_count = 0
        real_run = subprocess.run
        def mock_subprocess_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > 1:  # Baseline succeeds, mutant times out
                raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 10.0))
            return real_run(*args, **kwargs)

        with patch("subprocess.run", side_effect=mock_subprocess_run):
            res = run_mutation_tests(
                target_files=[src],
                repo_root=root,
                extra_pytest_args=[str(test)],
            )

        assert res.killed_mutants == res.total_mutants
        assert res.mutation_score == 100.0
        assert src.read_text(encoding="utf-8") == orig_text


def test_signal_handler_restores_mutated_file_on_sigint():
    """Verify that _mutation_signal_handler restores on-disk source on SIGINT before raising KeyboardInterrupt."""
    import signal
    from deployproof import mutator

    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "app.py"
        orig_code = "def add(a, b):\n    return a + b\n"
        mutated_code = "def add(a, b):\n    return a - b\n"
        src.write_text(mutated_code, encoding="utf-8")

        # Simulate active mutant tracking
        mutator._CURRENT_MUTATED_FILE = src
        mutator._CURRENT_ORIGINAL_CONTENT = orig_code

        try:
            mutator._mutation_signal_handler(signal.SIGINT, None)
        except KeyboardInterrupt:
            pass

        # The file on disk must be restored to orig_code
        assert src.read_text(encoding="utf-8") == orig_code
        assert mutator._CURRENT_MUTATED_FILE is None
        assert mutator._CURRENT_ORIGINAL_CONTENT is None


def test_signal_handler_restores_mutated_file_on_sigterm():
    """Verify that _mutation_signal_handler restores on-disk source on SIGTERM before process exit."""
    import signal
    from unittest.mock import patch
    from deployproof import mutator

    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "app.py"
        orig_code = "def multiply(a, b):\n    return a * b\n"
        mutated_code = "def multiply(a, b):\n    return a / b\n"
        src.write_text(mutated_code, encoding="utf-8")

        # Simulate active mutant tracking
        mutator._CURRENT_MUTATED_FILE = src
        mutator._CURRENT_ORIGINAL_CONTENT = orig_code

        with patch("sys.exit") as mock_exit:
            sig = getattr(signal, "SIGTERM", 15)
            mutator._mutation_signal_handler(sig, None)
            mock_exit.assert_called_once_with(128 + sig)

        # The file on disk must be restored to orig_code
        assert src.read_text(encoding="utf-8") == orig_code
        assert mutator._CURRENT_MUTATED_FILE is None
        assert mutator._CURRENT_ORIGINAL_CONTENT is None


def test_real_subprocess_os_signal_interrupt_restoration():
    """Verify that sending a real OS signal to a running deployproof process restores mutant files."""
    import os
    import signal
    import subprocess
    import sys
    import time

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        src_file = tmp_path / "calc.py"
        orig_code = (
            "def calculate(a: int, b: int, c: int) -> int:\n"
            "    res = 0\n"
            "    if a > 0 and b > 0:\n"
            "        res = a * b + 10\n"
            "    elif a <= 0 or b < 0:\n"
            "        res = a - b - 5\n"
            "    if c >= 100:\n"
            "        res = res * 2 + 50\n"
            "    else:\n"
            "        res = res // 2 - 1\n"
            "    return res + 1\n"
        )
        src_file.write_text(orig_code, encoding="utf-8")

        test_file = tmp_path / "test_calc.py"
        test_code = (
            "import time\n"
            "from calc import calculate\n\n"
            "def test_calculate():\n"
            "    time.sleep(0.4)\n"
            "    assert calculate(2, 3, 50) == 8\n"
        )
        test_file.write_text(test_code, encoding="utf-8")

        # Initialize temporary git repo
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_path), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True, check=True)
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True, check=True)

        # Modify calc.py to be in diff
        mod_code = orig_code + "\n# touch\n"
        src_file.write_text(mod_code, encoding="utf-8")

        repo_root = Path(__file__).resolve().parent.parent
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")

        cmd = [sys.executable, "-m", "deployproof.cli", "check", "--files", "calc.py"]
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0

        proc = subprocess.Popen(
            cmd,
            cwd=str(tmp_path),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
        )

        start_wait = time.time()
        mutant_detected = False
        while time.time() - start_wait < 15.0:
            if src_file.read_text(encoding="utf-8") != mod_code:
                mutant_detected = True
                break
            if proc.poll() is not None:
                break
            time.sleep(0.02)

        assert mutant_detected is True, "Mutant was not written to disk during the test window."

        if sys.platform == "win32":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.send_signal(signal.SIGINT)

        try:
            proc.communicate(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()

        # Target source file MUST be restored to original content immediately
        assert src_file.read_text(encoding="utf-8") == mod_code





