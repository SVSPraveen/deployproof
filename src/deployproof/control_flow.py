"""AST-based control flow and exception swallowing scanner for DeployProof."""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

from deployproof.diff import get_modified_line_ranges


@dataclass
class ControlFlowFinding:
    """Represents a control flow anomaly or swallowed exception detected in a Python file."""

    file_path: Path
    line_number: int
    rule_id: str  # 'bare_except', 'swallowed_exception', 'unreachable_code'
    severity: str  # 'WARNING'
    message: str
    snippet: str = ""


@dataclass
class ControlFlowScanSummary:
    """Summary of control flow and exception scan results."""

    total_findings: int
    findings: List[ControlFlowFinding] = field(default_factory=list)
    files_scanned: List[Path] = field(default_factory=list)


def _has_raise_node(nodes: List[ast.stmt]) -> bool:
    """Check if any statement in the list or its descendants contains an ast.Raise."""
    for stmt in nodes:
        for child in ast.walk(stmt):
            if isinstance(child, ast.Raise):
                return True
    return False


def _is_log_or_print_stmt(stmt: ast.stmt) -> bool:
    """Check if statement is purely a log call or print call."""
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        call = stmt.value
        if isinstance(call.func, ast.Name):
            if call.func.id in (
                "print",
                "log",
                "debug",
                "info",
                "warn",
                "warning",
                "error",
                "critical",
                "exception",
            ):
                return True
        elif isinstance(call.func, ast.Attribute):
            attr_name = call.func.attr.lower()
            if attr_name in (
                "debug",
                "info",
                "warn",
                "warning",
                "error",
                "critical",
                "exception",
                "log",
            ):
                return True
            if isinstance(call.func.value, ast.Name) and call.func.value.id.lower() in (
                "logging",
                "logger",
                "log",
            ):
                return True
    return False


def _is_empty_or_only_log_swallow(body: List[ast.stmt]) -> bool:
    """
    Check if an except handler body only contains pass, string docstrings,
    or log/print statements with no re-raise and no return of an error indicator.
    """
    if _has_raise_node(body):
        return False

    for stmt in body:
        for child in ast.walk(stmt):
            if isinstance(child, (ast.Return, ast.Yield, ast.YieldFrom)):
                return False

    # Check if all statements are pass, docstring, or log/print
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        ):
            continue
        if _is_log_or_print_stmt(stmt):
            continue
        # Contains other statements (e.g. fallback calculation or assignment)
        return False

    return True


def _is_broad_exception_type(node_type: Optional[ast.expr]) -> bool:
    """Check if exception type is Exception, BaseException, or a tuple containing them."""
    if node_type is None:
        return False
    if isinstance(node_type, ast.Name) and node_type.id in ("Exception", "BaseException"):
        return True
    if isinstance(node_type, ast.Attribute) and node_type.attr in ("Exception", "BaseException"):
        return True
    if isinstance(node_type, ast.Tuple):
        return any(_is_broad_exception_type(elt) for elt in node_type.elts)
    return False


class ControlFlowScanner(ast.NodeVisitor):
    """AST visitor to detect bare excepts, swallowed exceptions, and unreachable code."""

    def __init__(
        self,
        file_path: Path,
        source_lines: List[str],
        modified_lines: Optional[Set[int]] = None,
    ) -> None:
        self.file_path = file_path
        self.source_lines = source_lines
        self.modified_lines = modified_lines
        self.findings: List[ControlFlowFinding] = []
        self._seen_lines: Set[int] = set()

    def _get_snippet(self, lineno: int) -> str:
        if 0 < lineno <= len(self.source_lines):
            return self.source_lines[lineno - 1].strip()
        return ""

    def _record_finding(
        self,
        lineno: int,
        rule_id: str,
        message: str,
        snippet: Optional[str] = None,
    ) -> None:
        if self.modified_lines is not None and lineno not in self.modified_lines:
            return
        if lineno in self._seen_lines and rule_id == "unreachable_code":
            return
        self._seen_lines.add(lineno)
        self.findings.append(
            ControlFlowFinding(
                file_path=self.file_path,
                line_number=lineno,
                rule_id=rule_id,
                severity="WARNING",
                message=message,
                snippet=snippet or self._get_snippet(lineno),
            )
        )

    def _check_unreachable_statements_in_block(self, block: List[ast.stmt]) -> None:
        """Check for unreachable statements following unconditional return, raise, break, continue."""
        terminator_seen = False
        terminator_stmt: Optional[ast.stmt] = None

        for stmt in block:
            if terminator_seen and terminator_stmt:
                t_name = type(terminator_stmt).__name__.lower()
                self._record_finding(
                    lineno=stmt.lineno,
                    rule_id="unreachable_code",
                    message=f"Unreachable code detected after unconditional '{t_name}' on line {terminator_stmt.lineno}",
                )
            elif isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                terminator_seen = True
                terminator_stmt = stmt

    def generic_visit(self, node: ast.AST) -> None:
        # Check statement blocks on AST nodes that have a body/orelse/finalbody
        for attr in ("body", "orelse", "finalbody"):
            block = getattr(node, attr, None)
            if isinstance(block, list) and block and isinstance(block[0], ast.stmt):
                self._check_unreachable_statements_in_block(block)
        super().generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        # 1. Bare except: with no exception type
        if node.type is None:
            # If body contains a re-raise, it is a legitimate cleanup handler with re-raise
            if not _has_raise_node(node.body):
                self._record_finding(
                    lineno=node.lineno,
                    rule_id="bare_except",
                    message="Bare 'except:' handler without re-raise catches all exceptions (including SystemExit/KeyboardInterrupt)",
                )
        # 2. Broad except Exception / BaseException swallowed
        elif _is_broad_exception_type(node.type):
            if _is_empty_or_only_log_swallow(node.body):
                exc_type_str = getattr(node.type, "id", "Exception")
                self._record_finding(
                    lineno=node.lineno,
                    rule_id="swallowed_exception",
                    message=f"Broad 'except {exc_type_str}:' silently swallowed with no re-raise or error return",
                )

        self.generic_visit(node)


def scan_file_for_control_flow(
    file_path: Path,
    root: Path,
    base: Optional[str] = None,
    full_repo: bool = False,
) -> List[ControlFlowFinding]:
    """Scan a Python file for bare excepts, swallowed exceptions, and unreachable code."""
    if not file_path.is_file() or file_path.suffix != ".py":
        return []

    try:
        source_code = file_path.read_text(encoding="utf-8-sig", errors="replace")
        tree = ast.parse(source_code, filename=str(file_path))
    except Exception:
        return []

    if full_repo:
        modified_lines = None
    else:
        modified_lines = get_modified_line_ranges(file_path=file_path, root=root, base=base)
    source_lines = source_code.splitlines()

    scanner = ControlFlowScanner(
        file_path=file_path,
        source_lines=source_lines,
        modified_lines=modified_lines,
    )
    scanner.visit(tree)
    return scanner.findings


def scan_session_files_for_control_flow(
    session_files: List[Path],
    root: Path,
    base: Optional[str] = None,
    full_repo: bool = False,
) -> ControlFlowScanSummary:
    """Scan all modified session Python files for control flow and error handling issues."""
    all_findings: List[ControlFlowFinding] = []
    scanned_files: List[Path] = []

    for f in session_files:
        if f.is_file() and f.suffix == ".py":
            scanned_files.append(f)
            findings = scan_file_for_control_flow(file_path=f, root=root, base=base, full_repo=full_repo)
            all_findings.extend(findings)

    return ControlFlowScanSummary(
        total_findings=len(all_findings),
        findings=all_findings,
        files_scanned=scanned_files,
    )