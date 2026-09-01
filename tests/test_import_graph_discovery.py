import pytest
from pathlib import Path
from deployproof.mutator import discover_target_tests, _build_test_import_map

def test_non_matching_filename_test_discovery(tmp_path: Path):
    """
    Test that a source file (core.py) tested by a non-matching test file (test_commands.py)
    is correctly discovered via the import graph.
    """
    pkg_dir = tmp_path / "my_pkg"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("from .core import execute\n", encoding="utf-8")
    core_file = pkg_dir / "core.py"
    core_file.write_text("def execute(): return 42\n", encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True)
    test_commands = tests_dir / "test_commands.py"
    test_commands.write_text(
        "from my_pkg.core import execute\n\ndef test_exec():\n    assert execute() == 42\n",
        encoding="utf-8"
    )

    discovered = discover_target_tests([core_file], tmp_path)
    assert any("test_commands.py" in str(t) for t in discovered)

def test_directory_nested_test_discovery(tmp_path: Path):
    """
    Test that a source file (utils.py) tested inside a directory (tests/test_utils/test_style.py)
    is correctly discovered.
    """
    pkg_dir = tmp_path / "my_pkg"
    pkg_dir.mkdir(parents=True)
    utils_file = pkg_dir / "utils.py"
    utils_file.write_text("def format_text(s): return s.upper()\n", encoding="utf-8")

    test_sub_dir = tmp_path / "tests" / "test_utils"
    test_sub_dir.mkdir(parents=True)
    test_style = test_sub_dir / "test_style.py"
    test_style.write_text(
        "import my_pkg.utils\n\ndef test_format():\n    assert my_pkg.utils.format_text('hi') == 'HI'\n",
        encoding="utf-8"
    )

    discovered = discover_target_tests([utils_file], tmp_path)
    assert any("test_style.py" in str(t) for t in discovered)

def test_genuinely_untested_orphan_file(tmp_path: Path):
    """
    Test that a genuinely untested orphan file returns an empty test list.
    """
    pkg_dir = tmp_path / "my_pkg"
    pkg_dir.mkdir(parents=True)
    orphan_file = pkg_dir / "orphan.py"
    orphan_file.write_text("def unused(): return 0\n", encoding="utf-8")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_unrelated.py").write_text("def test_dummy(): pass\n", encoding="utf-8")

    discovered = discover_target_tests([orphan_file], tmp_path)
    assert discovered == []
