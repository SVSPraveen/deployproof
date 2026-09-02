"""Tests for AST mutant generation and transformer logic."""

import ast
import subprocess
import tempfile
from pathlib import Path
from deployproof.mutator import (
    generate_mutants_for_file,
    MutationCounter,
    MutationTransformer,
    _run_mutation_tests_sequential,
    run_mutation_tests_parallel,
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

        # Lines with logging/print should NOT have mutants
        # Line 6: logger.error(...)
        # Line 7: print(...)
        assert 6 not in lines_mutated
        assert 7 not in lines_mutated
        # String concatenation inside exception message should not have binary operator mutants
        assert not any("Replace binary operator" in m.description for m in mutants if m.line_number == 8)

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
            cmd = args[0] if args else kwargs.get("args", [])
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "-x" in cmd_str:  # Mutant test execution times out
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 10.0))
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

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
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

        # Modify calc.py to be in diff with an executable mutation target
        mod_code = orig_code.replace("return res + 1", "return res + 2")
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
        while time.time() - start_wait < 30.0:
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
        time.sleep(0.2)


def test_restore_removes_pyc_cache_file():
    """Verify that _restore_current_mutant_file unlinks the exact .pyc cache file without removing other cache files."""
    import importlib.util
    import py_compile
    from deployproof import mutator

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir).resolve()
        src1 = tmp_path / "module1.py"
        src1.write_text("def func1(): return 1\n", encoding="utf-8")
        src2 = tmp_path / "module2.py"
        src2.write_text("def func2(): return 2\n", encoding="utf-8")

        # Compile both to generate .pyc files in __pycache__
        py_compile.compile(str(src1), doraise=True)
        py_compile.compile(str(src2), doraise=True)

        pyc1_path = Path(importlib.util.cache_from_source(str(src1)))
        pyc2_path = Path(importlib.util.cache_from_source(str(src2)))

        assert pyc1_path.is_file(), "pyc1 should exist before restoration"
        assert pyc2_path.is_file(), "pyc2 should exist before restoration"

        # Simulate active mutant tracking on src1
        mutator._CURRENT_MUTATED_FILE = src1
        mutator._CURRENT_ORIGINAL_CONTENT = "def func1(): return 100\n"

        # Trigger restoration (as happens on interrupt / atexit)
        mutator._restore_current_mutant_file()

        # src1 should be restored and its specific .pyc removed
        assert src1.read_text(encoding="utf-8") == "def func1(): return 100\n"
        assert not pyc1_path.exists(), "src1's specific .pyc must be deleted"
        assert pyc2_path.is_file(), "unrelated src2's .pyc must remain intact"


def test_error_traces_to_mutant_fixture_crash_vs_unrelated_env_error():
    """Verify that fixture/setup errors referencing the mutated code are classified as KILLED, while unanchored errors remain RUNNER_ERROR."""
    from deployproof.mutator import Mutant, _error_traces_to_mutant

    mutant = Mutant(
        mutant_id="1",
        file_path=Path("src/requests/structures.py"),
        line_number=55,
        description="Replace comparison 'is' with 'is not'",
        original_line="if data is None:",
        mutated_line="if data is not None:",
        mutated_source="...",
    )

    # Case 1: Fixture error traceback directly referencing structures.py
    anchored_traceback = """
_________ ERROR at setup of TestCaseInsensitiveDict.test_list __________
    @pytest.fixture(autouse=True)
    def setup(self):
>       self.case_insensitive_dict = CaseInsensitiveDict()
tests/test_structures.py:10: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
    def __init__(self, data=None, **kwargs):
        self._store = OrderedDict()
        if data is not None:
            data = {}
>       self.update(data, **kwargs)
src/requests/structures.py:57: 
E   TypeError: 'NoneType' object is not iterable
"""
    assert _error_traces_to_mutant(anchored_traceback, mutant) is True

    # Case 2: Synthetic unanchored environment / third-party error
    unanchored_traceback = """
==================================== ERRORS ====================================
________________________ ERROR collecting test_external.py _____________________
ImportError while importing test module /tmp/tests/test_external.py.
Traceback:
/usr/lib/python3.10/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name, package, level)
E   ModuleNotFoundError: No module named 'unrelated_dependency'
"""
    assert _error_traces_to_mutant(unanchored_traceback, mutant) is False


def test_reporter_score_fraction_formatting_with_and_without_runner_errors():
    """Verify that reporter displays truthful fraction when runner errors are present vs clean."""
    from deployproof.mutator import Mutant, MutationResult
    from deployproof.reporter import format_report

    m1 = Mutant("1", Path("app.py"), 10, "desc", "orig", "mut", "src", status="KILLED")
    m2 = Mutant("2", Path("app.py"), 20, "desc", "orig", "mut", "src", status="KILLED")
    m3 = Mutant("3", Path("app.py"), 30, "desc", "orig", "mut", "src", status="KILLED")
    m4 = Mutant("4", Path("app.py"), 40, "desc", "orig", "mut", "src", status="KILLED")
    m_err = Mutant("5", Path("app.py"), 50, "desc", "orig", "mut", "src", status="RUNNER_ERROR")

    # Case A: With 1 runner error excluded (4 killed out of 4 valid, 5 total)
    res_with_err = MutationResult(
        total_mutants=5,
        killed_mutants=4,
        survived_mutants=[],
        runner_errors=[(m_err, "Pytest exit code 2: SyntaxError")],
        mutation_score=100.0,
        duration_seconds=1.23,
    )
    report_err = format_report(res_with_err, [Path("app.py")])
    assert "Score:  100.0% (4/4 valid mutants killed, 1 error excluded)" in report_err
    assert "Runner Errors (1 error excluded from score):" in report_err

    # Case B: Without runner errors (5 killed out of 5 total)
    res_clean = MutationResult(
        total_mutants=5,
        killed_mutants=5,
        survived_mutants=[],
        runner_errors=[],
        mutation_score=100.0,
        duration_seconds=1.23,
    )
    report_clean = format_report(res_clean, [Path("app.py")])
    assert "Score:  100.0% (5/5 mutants killed)" in report_clean
    assert "Runner Errors" not in report_clean


def test_parallel_mutation_runner_sandbox_isolation(tmp_path: Path):
    """Verify that run_mutation_tests in parallel mode executes workers in isolated sandboxes."""
    from deployproof.mutator import run_mutation_tests

    # 1. Setup repo files
    src1 = tmp_path / "math_ops.py"
    src1.write_text("def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n", encoding="utf-8")

    src2 = tmp_path / "str_ops.py"
    src2.write_text("def is_nonempty(s):\n    return len(s) > 0\n", encoding="utf-8")

    test1 = tmp_path / "test_math_ops.py"
    test1.write_text("from math_ops import add, sub\ndef test_math():\n    assert add(1, 2) == 3\n    assert sub(5, 2) == 3\n", encoding="utf-8")

    test2 = tmp_path / "test_str_ops.py"
    test2.write_text("from str_ops import is_nonempty\ndef test_str():\n    assert is_nonempty('a') is True\n    assert is_nonempty('') is False\n", encoding="utf-8")

    # 2. Run parallel mutation testing with 2 workers
    res = run_mutation_tests(
        target_files=[src1, src2],
        repo_root=tmp_path,
        workers=2,
        is_full_repo=True,
        quiet=True,
    )

    assert res.total_mutants >= 4
    assert res.killed_mutants == res.total_mutants
    assert res.mutation_score == 100.0
    assert len(res.untested_files) == 0
    assert len(res.runner_errors) == 0

    # Ensure source files are preserved
    assert "def add(a, b):\n    return a + b" in src1.read_text(encoding="utf-8")
    assert "def is_nonempty(s):\n    return len(s) > 0" in src2.read_text(encoding="utf-8")


def test_coverage_guided_test_selection_fixture(tmp_path: Path):
    """
    Verify coverage-guided test selection:
    (a) Mutants in specific functions receive only their covering test nodeids.
    (b) Mutants on module-level constants fall back to the full file correctly.
    (c) Final mutation score and kill counts match full-file sequential execution.
    """
    src_dir = tmp_path / "src" / "pkg"
    src_dir.mkdir(parents=True)
    service_file = src_dir / "service.py"
    service_file.write_text(
        "DEFAULT_LIMIT = 50\n"
        "\n"
        "def compute_tax(amount: float) -> float:\n"
        "    return amount * 0.1\n"
        "\n"
        "def compute_discount(amount: float) -> float:\n"
        "    return amount * 0.2\n",
        encoding="utf-8",
    )

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True)
    test_file = tests_dir / "test_service.py"
    test_file.write_text(
        "from pkg.service import compute_tax, compute_discount, DEFAULT_LIMIT\n"
        "\n"
        "def test_default_limit():\n"
        "    assert DEFAULT_LIMIT == 50\n"
        "\n"
        "def test_tax():\n"
        "    assert compute_tax(100.0) == 10.0\n"
        "\n"
        "def test_discount():\n"
        "    assert compute_discount(100.0) == 20.0\n",
        encoding="utf-8",
    )

    # 1. Run sequential (full-file test execution)
    res_seq = _run_mutation_tests_sequential([service_file], repo_root=tmp_path)

    # 2. Run parallel (coverage-guided minimal test selection)
    res_par = run_mutation_tests_parallel([service_file], repo_root=tmp_path, workers=2, quiet=True)

    # Assert matching outcomes
    assert res_seq.total_mutants == res_par.total_mutants
    assert res_seq.killed_mutants == res_par.killed_mutants
    assert res_seq.mutation_score == res_par.mutation_score
    assert res_par.mutation_score == 100.0
    assert len(res_par.untested_files) == 0
    assert len(res_par.runner_errors) == 0


def test_collection_crash_classified_as_killed_vs_unanchored_runner_error(tmp_path: Path):
    """
    Verify collection crashes (pytest exit code 2):
    - Mutation-caused collection crash referencing the mutated file/line -> KILLED
    - Unanchored / unrelated collection error -> RUNNER_ERROR
    """
    from deployproof.mutator import _run_single_mutant_in_sandbox, Mutant, _error_traces_to_mutant

    # Case A: Collection crash caused directly by mutated module
    snap = tmp_path / "snapshot"
    snap.mkdir()
    src = snap / "module.py"
    src.write_text("def get_items():\n    return [1, 2, 3]\n", encoding="utf-8")

    test = snap / "test_module.py"
    test.write_text("import module\nassert len(module.get_items()) == 3\n", encoding="utf-8")

    temp_base = tmp_path / "workers"
    temp_base.mkdir()
    pp = str(snap)

    res_mut = _run_single_mutant_in_sandbox(
        str(temp_base), str(snap), "module.py",
        "mod:2:mut1", 2, "Replace return list with None",
        "return [1, 2, 3]", "return None",
        "def get_items():\n    return None\n",
        ["test_module.py"], 0, 10.0, pp
    )
    assert res_mut["status"] == "KILLED"

    # Case B: Unanchored collection error (e.g. broken external test)
    unanchored_error_output = (
        "ERROR collecting test_unrelated.py\n"
        "ModuleNotFoundError: No module named 'nonexistent_package'\n"
    )
    mutant = Mutant("1", Path("module.py"), 1, "desc", "orig", "mut", "src")
    assert _error_traces_to_mutant(unanchored_error_output, mutant) is False


def test_cleanup_stale_deployproof_temp_dirs(tmp_path: Path, monkeypatch):
    """Verify startup cleanup safely purges stale dead-PID temp dirs while preserving live-PID dirs."""
    import os
    from deployproof.mutator import cleanup_stale_deployproof_temp_dirs, _ACTIVE_TEMP_DIRS

    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))

    # 1. Create a stale dir with a non-existent dead PID marker (e.g. 9999999)
    stale_dir = tmp_path / "deployproof_workers_stale999"
    stale_dir.mkdir()
    (stale_dir / ".deployproof_pid_9999999").touch()
    (stale_dir / "dummy.txt").write_text("old file", encoding="utf-8")

    # 2. Create an active dir with our current process's live PID marker
    live_dir = tmp_path / "deployproof_workers_live123"
    live_dir.mkdir()
    (live_dir / f".deployproof_pid_{os.getpid()}").touch()
    (live_dir / "active.txt").write_text("current file", encoding="utf-8")

    # 3. Create a dir currently registered in _ACTIVE_TEMP_DIRS
    tracked_dir = tmp_path / "deployproof_workers_tracked456"
    tracked_dir.mkdir()
    _ACTIVE_TEMP_DIRS.add(tracked_dir)

    try:
        cleaned_count = cleanup_stale_deployproof_temp_dirs()
        assert cleaned_count >= 1
        assert not stale_dir.exists()
        assert live_dir.exists()
        assert tracked_dir.exists()
    finally:
        _ACTIVE_TEMP_DIRS.discard(tracked_dir)


def test_cleanup_active_temp_dirs(tmp_path: Path):
    """Verify _cleanup_active_temp_dirs purges all tracked worker directories on exit/signal."""
    from deployproof.mutator import _cleanup_active_temp_dirs, _ACTIVE_TEMP_DIRS

    d1 = tmp_path / "deployproof_workers_test1"
    d2 = tmp_path / "deployproof_workers_test2"
    d1.mkdir()
    d2.mkdir()
    (d1 / "test.txt").write_text("hello", encoding="utf-8")
    (d2 / "test.txt").write_text("world", encoding="utf-8")

    _ACTIVE_TEMP_DIRS.add(d1)
    _ACTIVE_TEMP_DIRS.add(d2)

    assert len(_ACTIVE_TEMP_DIRS) == 2
    _cleanup_active_temp_dirs()

def test_calculate_baseline_timeout(tmp_path: Path):
    """Verify _calculate_baseline_timeout scales properly with file count, size, and multi-file suites."""
    from deployproof.mutator import _calculate_baseline_timeout

    # 1. Single small test file
    t1 = tmp_path / "test_small.py"
    t1.write_text("def test_one(): assert 1 == 1\n", encoding="utf-8")

    to_single = _calculate_baseline_timeout([str(t1)], tmp_path, test_runner_timeout=10.0)
    assert to_single == 60.0  # Floor minimum is 60.0s

    # 2. Multiple test files
    test_files = []
    for i in range(5):
        tf = tmp_path / f"test_{i}.py"
        tf.write_text("def test(): pass\n", encoding="utf-8")
        test_files.append(str(tf))

    to_multi = _calculate_baseline_timeout(test_files, tmp_path, test_runner_timeout=10.0)
    # 5 files * 35.0s = 175.0s, with multi_file_factor 1.25x -> 218.8s
    assert to_multi >= 218.0

    # 3. Large test file
    large_test = tmp_path / "test_large.py"
    large_content = "def test_chunk(): pass\n" * 5000  # ~115 KB
    large_test.write_text(large_content, encoding="utf-8")
    
    to_large = _calculate_baseline_timeout([str(large_test)], tmp_path, test_runner_timeout=10.0)
    # ~115 KB * 2.5s = ~287.5s
    assert to_large >= 250.0


def test_cleanup_stale_deployproof_temp_dirs_preserves_live_pids(tmp_path: Path, monkeypatch):
    """Verify cleanup_stale_deployproof_temp_dirs deletes dead PIDs but never touches active PIDs."""
    import os
    from deployproof.mutator import cleanup_stale_deployproof_temp_dirs

    # Mock tempdir to tmp_path
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))

    # Create active dir with current process PID
    active_dir = tmp_path / "deployproof_workers_active_test"
    active_dir.mkdir()
    (active_dir / f".deployproof_pid_{os.getpid()}").touch()
    (active_dir / "keep_me.txt").write_text("data", encoding="utf-8")

    # Create stale dir with fake dead PID
    stale_dir = tmp_path / "deployproof_workers_stale_test"
    stale_dir.mkdir()
    (stale_dir / ".deployproof_pid_9999999").touch()
    (stale_dir / "delete_me.txt").write_text("stale", encoding="utf-8")

    cleaned = cleanup_stale_deployproof_temp_dirs()
    assert cleaned >= 1
    assert active_dir.is_dir()
    assert not stale_dir.is_dir()


