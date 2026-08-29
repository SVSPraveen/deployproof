"""AST-based mock introduction detector for DeployProof."""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set, Tuple

from deployproof.diff import get_modified_line_ranges, is_test_file


@dataclass
class MockFinding:
    """Represents a mock usage or import detected in a test file."""
    file_path: Path
    line_number: int
    mock_type: str
    description: str
    snippet: str = ""


@dataclass
class MockScanSummary:
    """Summary of mock usage detection across scanned test files."""
    total_findings: int
    findings: List[MockFinding] = field(default_factory=list)
    files_scanned: List[Path] = field(default_factory=list)


class MockDetector(ast.NodeVisitor):
    """
    AST visitor to detect unittest.mock imports, mocker fixtures,
    monkeypatch fixtures, and patch calls/decorators.
    """

    def __init__(
        self,
        file_path: Path,
        source_lines: List[str],
        modified_lines: Optional[Set[int]] = None,
    ) -> None:
        self.file_path = file_path
        self.source_lines = source_lines
        self.modified_lines = modified_lines
        self.findings: List[MockFinding] = []
        self._seen_lines_and_types: Set[Tuple[int, str]] = set()
        self._decorator_call_nodes: Set[int] = set()

    def _add_finding(self, lineno: int, mock_type: str, description: str) -> None:
        if self.modified_lines is not None and lineno not in self.modified_lines:
            return
        key = (lineno, mock_type)
        if key in self._seen_lines_and_types:
            return
        self._seen_lines_and_types.add(key)
        snippet = (
            self.source_lines[lineno - 1].strip()
            if 0 <= lineno - 1 < len(self.source_lines)
            else ""
        )
        self.findings.append(
            MockFinding(
                file_path=self.file_path,
                line_number=lineno,
                mock_type=mock_type,
                description=description,
                snippet=snippet,
            )
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if (
                alias.name == "unittest.mock"
                or alias.name.startswith("unittest.mock.")
                or alias.name == "mock"
                or alias.name == "pytest_mock"
            ):
                self._add_finding(
                    node.lineno,
                    "mock_import",
                    f"Import {alias.name}",
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        if (
            mod == "unittest.mock"
            or mod.startswith("unittest.mock.")
            or mod == "mock"
            or mod == "pytest_mock"
        ):
            names = ", ".join(a.name for a in node.names)
            self._add_finding(
                node.lineno,
                "mock_import",
                f"from {mod} import {names}",
            )
        elif mod == "unittest":
            for alias in node.names:
                if alias.name == "mock":
                    self._add_finding(
                        node.lineno,
                        "mock_import",
                        "from unittest import mock",
                    )
        self.generic_visit(node)

    def _check_decorators(self, node: ast.AST) -> None:
        decorators = getattr(node, "decorator_list", [])
        for dec in decorators:
            if isinstance(dec, ast.Call):
                self._decorator_call_nodes.add(id(dec))
            if self._is_patch_target_node(dec):
                lineno = getattr(dec, "lineno", getattr(node, "lineno", 1))
                self._add_finding(lineno, "patch_decorator", "@patch decorator")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._check_decorators(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_func(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_func(node)
        self.generic_visit(node)

    def _check_func(self, node: ast.AST) -> None:
        args = getattr(node, "args", None)
        if args:
            all_args = list(args.args) + list(getattr(args, "kwonlyargs", []))
            for arg in all_args:
                if arg.arg in ("mocker", "monkeypatch"):
                    lineno = getattr(arg, "lineno", getattr(node, "lineno", 1))
                    self._add_finding(
                        lineno,
                        f"{arg.arg}_fixture",
                        f"{arg.arg} fixture parameter in {getattr(node, 'name', 'function')}()",
                    )

        self._check_decorators(node)

    def _is_patch_target_node(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Call):
            return self._is_patch_func(node.func)
        return self._is_patch_func(node)

    def _is_patch_func(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name) and node.id in ("patch", "mock_patch"):
            return True
        if isinstance(node, ast.Attribute):
            if node.attr in ("patch", "object", "dict", "multiple"):
                return self._is_patch_func(node.value)
            if isinstance(node.value, ast.Name) and node.value.id in (
                "mock",
                "unittest_mock",
                "mocker",
            ):
                return True
        return False

    def visit_Call(self, node: ast.Call) -> None:
        # If this call is an @patch decorator call, it is already recorded as patch_decorator
        if id(node) in self._decorator_call_nodes:
            self.generic_visit(node)
            return

        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "monkeypatch":
                self._add_finding(
                    node.lineno,
                    "monkeypatch_call",
                    f"monkeypatch.{node.func.attr}() call",
                )
            elif isinstance(node.func.value, ast.Name) and node.func.value.id == "mocker":
                self._add_finding(
                    node.lineno,
                    "mocker_call",
                    f"mocker.{node.func.attr}() call",
                )
            elif self._is_patch_func(node.func):
                self._add_finding(
                    node.lineno,
                    "patch_call",
                    "patch(...) call",
                )
        elif isinstance(node.func, ast.Name):
            if node.func.id in ("patch", "mock_patch"):
                self._add_finding(
                    node.lineno,
                    "patch_call",
                    "patch(...) call",
                )
            elif node.func.id in (
                "MagicMock",
                "Mock",
                "AsyncMock",
                "PropertyMock",
                "create_autospec",
            ):
                self._add_finding(
                    node.lineno,
                    "mock_instantiation",
                    f"{node.func.id}(...) instantiation",
                )
        self.generic_visit(node)


def scan_test_file_for_mocks(
    file_path: Path,
    root: Optional[Path] = None,
    base: Optional[str] = None,
) -> List[MockFinding]:
    """Scan a single test file for newly introduced mock usages."""
    if not file_path.is_file():
        return []

    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    modified_lines: Optional[Set[int]] = None
    if root:
        try:
            modified_lines = get_modified_line_ranges(file_path, root, base=base)
        except Exception:
            modified_lines = None

    detector = MockDetector(file_path, source.splitlines(), modified_lines=modified_lines)
    detector.visit(tree)
    return detector.findings


def scan_session_files_for_mocks(
    session_files: List[Path],
    root: Optional[Path] = None,
    base: Optional[str] = None,
) -> MockScanSummary:
    """Scan all test files in session_files for newly introduced mock usages."""
    test_files = [f for f in session_files if f.is_file() and f.suffix == ".py" and is_test_file(f)]
    all_findings: List[MockFinding] = []

    for tf in test_files:
        findings = scan_test_file_for_mocks(tf, root=root, base=base)
        all_findings.extend(findings)

    return MockScanSummary(
        total_findings=len(all_findings),
        findings=all_findings,
        files_scanned=test_files,
    )
