"""Deterministic AST mutation testing engine for DeployProof."""
import ast
import atexit
import copy
import importlib.util
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

@dataclass
class Mutant:
    """Represents an individual code mutant."""
    mutant_id: str
    file_path: Path
    line_number: int
    description: str
    original_line: str
    mutated_line: str
    mutated_source: str
    status: str = 'PENDING'

@dataclass
class PrunedEquivalentMutant:
    """Represents an equivalent mutant or dead-code location pruned before execution."""
    file_path: Path
    line_number: int
    category: str
    description: str
    original_line: str = ''

@dataclass
class SkippedConstruct:
    """Represents an unsupported construct in source code that Tier 1 cannot mutate."""
    file_path: Path
    line_number: int
    construct_name: str
    description: str
    snippet: str = ''

@dataclass
class MutationResult:
    """Aggregated mutation testing results."""
    total_mutants: int
    killed_mutants: int
    survived_mutants: List[Mutant] = field(default_factory=list)
    untested_files: List[Path] = field(default_factory=list)
    runner_errors: List[Tuple[Mutant, str]] = field(default_factory=list)
    skipped_constructs: List[SkippedConstruct] = field(default_factory=list)
    pruned_equivalent_mutants: List[PrunedEquivalentMutant] = field(default_factory=list)
    mutation_score: Optional[float] = 100.0
    duration_seconds: float = 0.0
    files_tested: List[Path] = field(default_factory=list)
    collection_error: Optional[str] = None
_CURRENT_MUTATED_FILE: Optional[Path] = None
_CURRENT_ORIGINAL_CONTENT: Optional[str] = None
_ACTIVE_TEMP_DIRS: Set[Path] = set()
_SIGNAL_HANDLER_INSTALLED: bool = False
_PREV_SIGINT: Any = None
_PREV_SIGTERM: Any = None
_PREV_SIGBREAK: Any = None

def _on_rm_error(func: Any, path: str, exc_info: Any) -> None:
    """Clear Windows read-only attributes and retry file/directory removal."""
    try:
        import stat
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass

def _cleanup_active_temp_dirs() -> None:
    """Immediately remove all active temporary worker directories tracked by this process."""
    global _ACTIVE_TEMP_DIRS
    for temp_path in list(_ACTIVE_TEMP_DIRS):
        if temp_path.is_dir():
            try:
                shutil.rmtree(temp_path, onerror=_on_rm_error)
            except Exception:
                pass
    _ACTIVE_TEMP_DIRS.clear()

atexit.register(_cleanup_active_temp_dirs)

def cleanup_stale_deployproof_temp_dirs() -> int:
    """
    Scans the system temp directory for orphaned deployproof temp directories from
    previous interrupted or crashed runs (e.g. SIGKILL, forced termination, closed terminals).
    
    Safely skips directories actively in use by another running DeployProof instance.
    Returns the number of stale directories cleaned up.
    """
    if os.environ.get("DEPLOYPROOF_WORKER") == "1":
        return 0

    temp_dir = Path(tempfile.gettempdir())
    cleaned = 0

    def _is_pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if sys.platform == "win32":
            try:
                import ctypes
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                STILL_ACTIVE = 259
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if not handle:
                    err = kernel32.GetLastError()
                    if err == 5:  # ERROR_ACCESS_DENIED means process exists and is running
                        return True
                    return False
                exit_code = ctypes.c_ulong()
                success = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                kernel32.CloseHandle(handle)
                return bool(success and exit_code.value == STILL_ACTIVE)
            except Exception:
                return True  # If unable to inspect on Windows, assume alive to avoid deleting active dirs
        else:
            try:
                os.kill(pid, 0)
                return True
            except (OSError, ProcessLookupError, PermissionError):
                return False

    try:
        for d in temp_dir.glob("deployproof*"):
            if not d.is_dir():
                continue
            # Skip if it's one of our own currently active temp dirs
            if d in _ACTIVE_TEMP_DIRS:
                continue

            # Check for PID marker
            pid_markers = list(d.glob(".deployproof_pid_*"))
            is_stale = False
            if pid_markers:
                for marker in pid_markers:
                    try:
                        pid = int(marker.name.split("_")[-1])
                        if not _is_pid_alive(pid):
                            is_stale = True
                        else:
                            is_stale = False
                            break
                    except (ValueError, IndexError):
                        is_stale = True
            else:
                # No PID marker: if directory was created >120s ago, check if stale
                try:
                    mtime = d.stat().st_mtime
                    if (time.time() - mtime) > 120:
                        is_stale = True
                except Exception:
                    pass

            if is_stale:
                try:
                    shutil.rmtree(d, onerror=_on_rm_error)
                    cleaned += 1
                except Exception:
                    # In use by another process on Windows/Unix; rmtree will safely fail
                    pass
    except Exception:
        pass

    return cleaned

def _restore_current_mutant_file() -> None:
    """Immediately restore the currently mutated file on disk if one is active and clear its specific bytecode cache."""
    global _CURRENT_MUTATED_FILE, _CURRENT_ORIGINAL_CONTENT
    if _CURRENT_MUTATED_FILE is not None and _CURRENT_ORIGINAL_CONTENT is not None:
        target_path = _CURRENT_MUTATED_FILE
        try:
            target_path.write_text(_CURRENT_ORIGINAL_CONTENT, encoding="utf-8")
        except Exception as e:
            sys.stderr.write(
                f"\n[DeployProof WARNING] Failed to restore source file '{target_path}' "
                f"after interrupt/exit: {e}\n"
                f"Please verify this file's contents before committing or running tests.\n"
            )
            sys.stderr.flush()

        # Remove specific __pycache__ .pyc entry for target_path if it exists
        try:
            pyc_path_str = importlib.util.cache_from_source(str(target_path))
            if pyc_path_str:
                pyc_file = Path(pyc_path_str)
                if pyc_file.is_file():
                    pyc_file.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass

        _CURRENT_MUTATED_FILE = None
        _CURRENT_ORIGINAL_CONTENT = None
atexit.register(_restore_current_mutant_file)

def _mutation_signal_handler(signum: int, frame: Any) -> None:
    """Signal handler for SIGINT, SIGTERM, and SIGBREAK to restore on-disk source and cleanup temp dirs before process exit."""
    _restore_current_mutant_file()
    _cleanup_active_temp_dirs()
    if signum in (getattr(signal, 'SIGINT', 2), getattr(signal, 'SIGBREAK', 21)):
        raise KeyboardInterrupt(f'Interrupted by signal {signum} during mutation testing')
    sys.exit(128 + signum)

def install_mutation_signal_handlers() -> None:
    """Install SIGINT, SIGTERM, and SIGBREAK handlers for mutation testing if not already active."""
    global _SIGNAL_HANDLER_INSTALLED, _PREV_SIGINT, _PREV_SIGTERM, _PREV_SIGBREAK
    if _SIGNAL_HANDLER_INSTALLED:
        return
    try:
        _PREV_SIGINT = signal.signal(signal.SIGINT, _mutation_signal_handler)
    except (ValueError, AttributeError):
        _PREV_SIGINT = None
    if hasattr(signal, 'SIGTERM'):
        try:
            _PREV_SIGTERM = signal.signal(signal.SIGTERM, _mutation_signal_handler)
        except (ValueError, AttributeError):
            _PREV_SIGTERM = None
    if hasattr(signal, 'SIGBREAK'):
        try:
            _PREV_SIGBREAK = signal.signal(signal.SIGBREAK, _mutation_signal_handler)
        except (ValueError, AttributeError):
            _PREV_SIGBREAK = None
    _SIGNAL_HANDLER_INSTALLED = True

def remove_mutation_signal_handlers() -> None:
    """Restore previous signal handlers after mutation testing completes."""
    global _SIGNAL_HANDLER_INSTALLED, _PREV_SIGINT, _PREV_SIGTERM, _PREV_SIGBREAK
    if not _SIGNAL_HANDLER_INSTALLED:
        return
    if _PREV_SIGINT is not None:
        try:
            signal.signal(signal.SIGINT, _PREV_SIGINT)
        except (ValueError, AttributeError):
            pass
        _PREV_SIGINT = None
    if _PREV_SIGTERM is not None and hasattr(signal, 'SIGTERM'):
        try:
            signal.signal(signal.SIGTERM, _PREV_SIGTERM)
        except (ValueError, AttributeError):
            pass
        _PREV_SIGTERM = None
    if _PREV_SIGBREAK is not None and hasattr(signal, 'SIGBREAK'):
        try:
            signal.signal(signal.SIGBREAK, _PREV_SIGBREAK)
        except (ValueError, AttributeError):
            pass
        _PREV_SIGBREAK = None
    _SIGNAL_HANDLER_INSTALLED = False
COMPARE_MAP = {ast.Eq: (ast.NotEq, '==', '!='), ast.NotEq: (ast.Eq, '!=', '=='), ast.Lt: (ast.GtE, '<', '>='), ast.LtE: (ast.Gt, '<=', '>'), ast.Gt: (ast.LtE, '>', '<='), ast.GtE: (ast.Lt, '>=', '<'), ast.In: (ast.NotIn, 'in', 'not in'), ast.NotIn: (ast.In, 'not in', 'in'), ast.Is: (ast.IsNot, 'is', 'is not'), ast.IsNot: (ast.Is, 'is not', 'is')}
BINOP_MAP = {
    ast.Add: (ast.Sub, '+', '-'),
    ast.Sub: (ast.Add, '-', '+'),
    ast.Mult: (ast.Div, '*', '/'),
    ast.Div: (ast.Mult, '/', '*'),
    ast.FloorDiv: (ast.Div, '//', '/'),
    ast.Mod: (ast.Mult, '%', '*'),
    ast.Pow: (ast.Mult, '**', '*'),
    ast.LShift: (ast.RShift, '<<', '>>'),
    ast.RShift: (ast.LShift, '>>', '<<'),
    ast.BitAnd: (ast.BitOr, '&', '|'),
    ast.BitOr: (ast.BitAnd, '|', '&'),
    ast.BitXor: (ast.BitAnd, '^', '&'),
}
BOOLOP_MAP = {ast.And: (ast.Or, 'and', 'or'), ast.Or: (ast.And, 'or', 'and')}
AUGASSIGN_MAP = {
    ast.Add: (ast.Sub, '+=', '-='),
    ast.Sub: (ast.Add, '-=', '+='),
    ast.Mult: (ast.Div, '*=', '/='),
    ast.Div: (ast.Mult, '/=', '*='),
    ast.FloorDiv: (ast.Div, '//=', '/='),
    ast.Mod: (ast.Div, '%=', '/='),
    ast.Pow: (ast.Mult, '**=', '*='),
    ast.LShift: (ast.RShift, '<<=', '>>='),
    ast.RShift: (ast.LShift, '>>=', '<<='),
    ast.BitAnd: (ast.BitOr, '&=', '|='),
    ast.BitOr: (ast.BitAnd, '|=', '&='),
    ast.BitXor: (ast.BitAnd, '^=', '&='),
}
UNARYOP_MAP = {ast.USub: (ast.UAdd, '-', '+'), ast.UAdd: (ast.USub, '+', '-')}
STRING_METHOD_SWAP = {
    'lower': 'upper',
    'upper': 'lower',
    'strip': 'rstrip',
    'lstrip': 'rstrip',
    'rstrip': 'lstrip',
    'find': 'rfind',
    'rfind': 'find',
    'index': 'rindex',
    'rindex': 'index',
    'split': 'rsplit',
    'rsplit': 'split',
    'partition': 'rpartition',
    'rpartition': 'partition',
    'ljust': 'rjust',
    'rjust': 'ljust',
    'startswith': 'endswith',
    'endswith': 'startswith',
    'removeprefix': 'removesuffix',
    'removesuffix': 'removeprefix',
}
EXCEPT_MAP = {
    'ValueError': 'ZeroDivisionError',
    'KeyError': 'IndexError',
    'TypeError': 'ValueError',
    'IndexError': 'KeyError',
    'AttributeError': 'TypeError',
}

def _is_special_builtin_call(call: ast.Call) -> bool:
    if isinstance(call.func, ast.Name):
        if call.func.id in ('isinstance', 'issubclass', 'getattr', 'setattr', 'hasattr', 'delattr', 'open', 'divmod', 'pow', 'is_log_or_print_call'):
            return True
    return False

def _is_type_checking_guard(node: ast.If) -> bool:
    """Check if an if-statement is guarding typing/TYPE_CHECKING imports."""
    if isinstance(node.test, ast.Name) and node.test.id in ('TYPE_CHECKING', 'type_checking'):
        return True
    if isinstance(node.test, ast.Attribute) and node.test.attr == 'TYPE_CHECKING':
        return True
    return False

def _is_overload_def(node: ast.AST) -> bool:
    """Check if a function definition is a static typing @overload stub."""
    for dec in getattr(node, 'decorator_list', []):
        if isinstance(dec, ast.Name) and dec.id == 'overload':
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == 'overload':
            return True
    return False

class SkippedConstructCollector(ast.NodeVisitor):
    """Identifies and records unsupported Python constructs during AST traversal."""

    def __init__(self, file_path: Path, source_lines: List[str]) -> None:
        self.file_path = file_path
        self.source_lines = source_lines
        self.skipped: List[SkippedConstruct] = []
        self._seen: Set[Tuple[int, str]] = set()

    def _record_skip(self, node: ast.AST, construct_name: str, description: str) -> None:
        lineno = getattr(node, 'lineno', 1)
        key = (lineno, construct_name)
        if key not in self._seen:
            self._seen.add(key)
            snippet = self.source_lines[lineno - 1].strip() if 0 <= lineno - 1 < len(self.source_lines) else ''
            self.skipped.append(SkippedConstruct(file_path=self.file_path, line_number=lineno, construct_name=construct_name, description=description, snippet=snippet))

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._record_skip(node, 'Walrus Operator (:=)', 'Walrus assignment expression target binding not mutated by Tier 1')
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        self._record_skip(node, 'Match Statement Pattern', 'Structural pattern matching shapes/rules not mutated by Tier 1')
        self.generic_visit(node)

    def visit_Yield(self, node: ast.Yield) -> None:
        self._record_skip(node, 'Yield Statement', 'Generator yield statement semantics not mutated by Tier 1')
        self.generic_visit(node)

    def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
        self._record_skip(node, 'Yield From Statement', 'Generator yield from statement semantics not mutated by Tier 1')
        self.generic_visit(node)

def is_log_or_print_call(call: ast.Call) -> bool:
    """Check if an AST Call node is a call to logging, logger, or print."""
    if isinstance(call.func, ast.Name):
        if call.func.id in ('print', 'log', 'debug', 'info', 'warn', 'warning', 'error', 'critical', 'exception'):
            return True
    elif isinstance(call.func, ast.Attribute):
        attr_name = call.func.attr.lower()
        if attr_name in ('debug', 'info', 'warn', 'warning', 'error', 'critical', 'exception', 'log'):
            return True
        if isinstance(call.func.value, ast.Name) and call.func.value.id.lower() in ('logging', 'logger', 'log'):
            return True
    return False

def _is_none_constant(node: Optional[ast.AST]) -> bool:
    if node is None:
        return True
    if isinstance(node, ast.Constant) and node.value is None:
        return True
    if isinstance(node, ast.Name) and node.id == "None":
        return True
    return False

def _is_docstring_expr(node: ast.AST) -> bool:
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
        return True
    return False

def _is_docstring_or_directive(node: ast.Constant) -> bool:
    if not isinstance(node.value, str):
        return True
    val = node.value
    if (val.startswith("__") and val.endswith("__")) or val in ("utf-8", "ascii", "r", "w", "a", "rb", "wb"):
        return True
    if len(val) > 300:
        return True
    return False

def _stmt_always_terminates(stmt: ast.stmt) -> bool:
    if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
        return True
    if isinstance(stmt, ast.If):
        if stmt.orelse and _block_always_terminates(stmt.body) and _block_always_terminates(stmt.orelse):
            return True
    return False

def _block_always_terminates(body: List[ast.stmt]) -> bool:
    for s in body:
        if _stmt_always_terminates(s):
            return True
    return False

class DeadCodeFinder(ast.NodeVisitor):
    """Identifies lines of code that are unreachable due to prior unconditional returns/raises/breaks."""

    def __init__(self) -> None:
        self.dead_lines: Set[int] = set()

    def _check_block(self, body: List[ast.stmt]) -> None:
        terminated = False
        for stmt in body:
            if terminated:
                lineno = getattr(stmt, "lineno", None)
                if lineno:
                    self.dead_lines.add(lineno)
                for child in ast.walk(stmt):
                    child_lineno = getattr(child, "lineno", None)
                    if child_lineno:
                        self.dead_lines.add(child_lineno)
            if _stmt_always_terminates(stmt):
                terminated = True
            self.visit(stmt)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_block(node.body)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_block(node.body)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        if isinstance(node.test, ast.Constant) and node.test.value is False:
            for s in node.body:
                if hasattr(s, "lineno"):
                    self.dead_lines.add(s.lineno)
                for c in ast.walk(s):
                    if hasattr(c, "lineno"):
                        self.dead_lines.add(c.lineno)
        else:
            self._check_block(node.body)
        if isinstance(node.test, ast.Constant) and node.test.value is True:
            for s in node.orelse:
                if hasattr(s, "lineno"):
                    self.dead_lines.add(s.lineno)
                for c in ast.walk(s):
                    if hasattr(c, "lineno"):
                        self.dead_lines.add(c.lineno)
        else:
            self._check_block(node.orelse)

    def visit_For(self, node: ast.For) -> None:
        self._check_block(node.body)
        self._check_block(node.orelse)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._check_block(node.body)
        self._check_block(node.orelse)

    def visit_While(self, node: ast.While) -> None:
        if isinstance(node.test, ast.Constant) and node.test.value is False:
            for s in node.body:
                if hasattr(s, "lineno"):
                    self.dead_lines.add(s.lineno)
                for c in ast.walk(s):
                    if hasattr(c, "lineno"):
                        self.dead_lines.add(c.lineno)
        else:
            self._check_block(node.body)
        self._check_block(node.orelse)

    def visit_Try(self, node: ast.Try) -> None:
        self._check_block(node.body)
        for h in node.handlers:
            self._check_block(h.body)
        self._check_block(node.orelse)
        self._check_block(node.finalbody)

    def visit_With(self, node: ast.With) -> None:
        self._check_block(node.body)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._check_block(node.body)


def is_algebraic_zero_identity(node: ast.AST) -> bool:
    """Check if binary operator is adding or subtracting 0 (e.g. x + 0 == x - 0)."""
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, (ast.Add, ast.Sub)):
            if isinstance(node.right, ast.Constant) and node.right.value == 0 and not isinstance(node.right.value, bool):
                return True
            if isinstance(node.left, ast.Constant) and node.left.value == 0 and not isinstance(node.left.value, bool) and isinstance(node.op, ast.Add):
                return True
    return False


def is_range_zero_start(node: ast.AST) -> bool:
    """Check if range call starts at 0 (range(0, N) == range(N))."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "range":
        if len(node.args) == 2 and isinstance(node.args[0], ast.Constant) and node.args[0].value == 0 and not isinstance(node.args[0].value, bool):
            return True
    return False


class EquivalentMutantCollector(ast.NodeVisitor):
    """Collects equivalent / unkillable mutant locations for reporting and pruning."""

    def __init__(self, file_path: Path, lines: List[str], dead_lines: Set[int], line_ranges: Optional[Set[int]] = None) -> None:
        self.file_path = file_path
        self.lines = lines
        self.dead_lines = dead_lines
        self.line_ranges = line_ranges
        self.pruned: List[PrunedEquivalentMutant] = []

    def _should_include(self, lineno: int) -> bool:
        if self.line_ranges is not None and lineno not in self.line_ranges:
            return False
        return True

    def visit_BinOp(self, node: ast.BinOp) -> None:
        lineno = getattr(node, "lineno", 1)
        if self._should_include(lineno) and is_algebraic_zero_identity(node):
            raw_line = self.lines[lineno - 1].strip() if 0 <= lineno - 1 < len(self.lines) else ""
            self.pruned.append(PrunedEquivalentMutant(
                file_path=self.file_path,
                line_number=lineno,
                category="Algebraic Identity",
                description="Arithmetic zero identity (x + 0 == x - 0)",
                original_line=raw_line,
            ))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        lineno = getattr(node, "lineno", 1)
        if self._should_include(lineno):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "get" and len(node.args) == 2:
                if isinstance(node.args[1], ast.Constant) and node.args[1].value is None:
                    raw_line = self.lines[lineno - 1].strip() if 0 <= lineno - 1 < len(self.lines) else ""
                    self.pruned.append(PrunedEquivalentMutant(
                        file_path=self.file_path,
                        line_number=lineno,
                        category="Defensive Redundancy",
                        description="dict.get() None default fallback (d.get(k, None) == d.get(k))",
                        original_line=raw_line,
                    ))
            elif is_range_zero_start(node):
                raw_line = self.lines[lineno - 1].strip() if 0 <= lineno - 1 < len(self.lines) else ""
                self.pruned.append(PrunedEquivalentMutant(
                    file_path=self.file_path,
                    line_number=lineno,
                    category="Redundant Range Boundary",
                    description="Range zero start index (range(0, N) == range(N))",
                    original_line=raw_line,
                ))
        self.generic_visit(node)


def collect_equivalent_mutants_for_file(
    file_path: Path,
    line_ranges: Optional[Set[int]] = None,
) -> List[PrunedEquivalentMutant]:
    """Scans a file for equivalent mutants, dead code, and redundant constructs."""
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except Exception:
        return []

    lines = source.splitlines()
    finder = DeadCodeFinder()
    finder.visit(tree)

    collector = EquivalentMutantCollector(file_path, lines, finder.dead_lines, line_ranges=line_ranges)
    collector.visit(tree)

    seen_dead_lines = set()
    for dl in sorted(list(finder.dead_lines)):
        if line_ranges is not None and dl not in line_ranges:
            continue
        if dl in seen_dead_lines:
            continue
        seen_dead_lines.add(dl)
        raw_line = lines[dl - 1].strip() if 0 <= dl - 1 < len(lines) else ""
        if raw_line and not raw_line.startswith("#"):
            collector.pruned.append(PrunedEquivalentMutant(
                file_path=file_path,
                line_number=dl,
                category="Dead Code / Unreachable",
                description="Code statement placed after unconditional terminating control flow",
                original_line=raw_line,
            ))

    return collector.pruned


class MutationCounter(ast.NodeVisitor):
    """Count number of mutable locations in an AST, excluding type annotations."""

    def __init__(self) -> None:
        self.count = 0

    def visit_Module(self, node: ast.Module) -> None:
        for idx, stmt in enumerate(node.body):
            if idx == 0 and _is_docstring_expr(stmt):
                continue
            self.visit(stmt)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.count += len(node.decorator_list)
        for b in node.bases:
            self.visit(b)
        for idx, stmt in enumerate(node.body):
            if idx == 0 and _is_docstring_expr(stmt):
                continue
            self.visit(stmt)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if _is_overload_def(node):
            return
        self.count += len(node.decorator_list)
        for default in node.args.defaults:
            if default:
                self.visit(default)
        for kw_default in node.args.kw_defaults:
            if kw_default:
                self.visit(kw_default)
        for idx, stmt in enumerate(node.body):
            if idx == 0 and _is_docstring_expr(stmt):
                continue
            self.visit(stmt)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if _is_overload_def(node):
            return
        self.count += len(node.decorator_list)
        for default in node.args.defaults:
            if default:
                self.visit(default)
        for kw_default in node.args.kw_defaults:
            if kw_default:
                self.visit(kw_default)
        for idx, stmt in enumerate(node.body):
            if idx == 0 and _is_docstring_expr(stmt):
                continue
            self.visit(stmt)

    def visit_With(self, node: ast.With) -> None:
        if all(item.optional_vars is None for item in node.items):
            self.count += 1
        for stmt in node.body:
            self.visit(stmt)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        if all(item.optional_vars is None for item in node.items):
            self.count += 1
        for stmt in node.body:
            self.visit(stmt)

    def visit_For(self, node: ast.For) -> None:
        if not (isinstance(node.iter, ast.List) and len(node.iter.elts) == 0):
            self.count += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        if not (isinstance(node.iter, ast.List) and len(node.iter.elts) == 0):
            self.count += 1
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking_guard(node):
            return
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if isinstance(node.type, ast.Name) and node.type.id in EXCEPT_MAP:
            self.count += 1
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        node_target = getattr(node, 'target', None)
        if node_target:
            self.visit(node_target)
        if node.value:
            self.visit(node.value)

    def visit_arg(self, node: ast.arg) -> None:
        pass

    def visit_Await(self, node: ast.Await) -> None:
        self.count += 1
        self.generic_visit(node)

    def visit_Break(self, node: ast.Break) -> None:
        self.count += 1

    def visit_Continue(self, node: ast.Continue) -> None:
        self.count += 1

    def visit_Call(self, node: ast.Call) -> None:
        if is_log_or_print_call(node):
            return
        if isinstance(node.func, ast.Attribute) and node.func.attr in STRING_METHOD_SWAP:
            self.count += 1
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "get" and len(node.args) == 2 and not _is_none_constant(node.args[1]):
            self.count += 1
        elif len(node.args) == 2 and not _is_special_builtin_call(node):
            self.count += 1
        self.generic_visit(node)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        if type(node.op) in UNARYOP_MAP or isinstance(node.op, (ast.Not, ast.Invert)):
            self.count += 1
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        if not _is_none_constant(node.value):
            self.count += 1
            self.visit(node.value)

    def visit_Assert(self, node: ast.Assert) -> None:
        self.count += 1
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        if isinstance(node.value, ast.Call) and not is_log_or_print_call(node.value):
            self.count += 1
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        self.count += 1
        if isinstance(node.exc, ast.Call):
            for arg in node.exc.args:
                if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)) and (not (isinstance(arg, ast.BinOp) and isinstance(arg.op, (ast.Add, ast.Mod)))):
                    self.visit(arg)
            if node.cause:
                self.visit(node.cause)
            return
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        for op in node.ops:
            if type(op) in COMPARE_MAP:
                self.count += 1
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if type(node.op) in BINOP_MAP:
            self.count += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        if type(node.op) in BOOLOP_MAP:
            self.count += 1
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if type(node.op) in AUGASSIGN_MAP:
            self.count += 1
        self.generic_visit(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.count += 1
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "deepcopy":
            self.count += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.count += 1
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        if node.ifs:
            self.count += len(node.ifs)
        self.generic_visit(node)

    def visit_Yield(self, node: ast.Yield) -> None:
        self.count += 1
        self.generic_visit(node)

    def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
        self.count += 1
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        if len(node.cases) > 1:
            self.count += len(node.cases)
        for case in node.cases:
            if case.guard:
                self.count += 1
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, bool):
            self.count += 1
        elif isinstance(node.value, (int, float)) and (not isinstance(node.value, bool)):
            self.count += 1
        elif isinstance(node.value, str) and not _is_docstring_or_directive(node):
            self.count += 1
        self.generic_visit(node)

class MutationTransformer(ast.NodeTransformer):
    """Applies a single mutation at the specified index, excluding type annotations."""

    def __init__(self, target_index: int) -> None:
        self.target_index = target_index
        self.current_index = 0
        self.applied_info: Optional[Tuple[int, str, str, str]] = None

    def visit_Module(self, node: ast.Module) -> ast.AST:
        new_body = []
        for idx, stmt in enumerate(node.body):
            if idx == 0 and _is_docstring_expr(stmt):
                new_body.append(stmt)
            else:
                new_body.append(self.visit(stmt))
        node.body = new_body
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        for d_idx, d in enumerate(list(node.decorator_list)):
            if self.current_index == self.target_index:
                lineno = getattr(d, 'lineno', getattr(node, 'lineno', 1))
                dec_name = getattr(d, 'id', getattr(getattr(d, 'func', None), 'id', 'decorator'))
                self.applied_info = (lineno, f"Remove class decorator @{dec_name}", f"@{dec_name}", "", None, None)
                node.decorator_list = [dec for i, dec in enumerate(node.decorator_list) if i != d_idx]
                self.current_index += 1
                break
            self.current_index += 1
        node.bases = [self.visit(b) for b in node.bases]
        new_body = []
        for idx, stmt in enumerate(node.body):
            if idx == 0 and _is_docstring_expr(stmt):
                new_body.append(stmt)
            else:
                res = self.visit(stmt)
                if isinstance(res, list):
                    new_body.extend(res)
                elif res is not None:
                    new_body.append(res)
        node.body = new_body
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        if _is_overload_def(node):
            return node
        for d_idx, d in enumerate(list(node.decorator_list)):
            if self.current_index == self.target_index:
                lineno = getattr(d, 'lineno', getattr(node, 'lineno', 1))
                dec_name = getattr(d, 'id', getattr(getattr(d, 'func', None), 'id', 'decorator'))
                self.applied_info = (lineno, f"Remove function decorator @{dec_name}", f"@{dec_name}", "", None, None)
                node.decorator_list = [dec for i, dec in enumerate(node.decorator_list) if i != d_idx]
                self.current_index += 1
                break
            self.current_index += 1
        node.args.defaults = [self.visit(d) if d else None for d in node.args.defaults]
        node.args.kw_defaults = [self.visit(d) if d else None for d in node.args.kw_defaults]
        new_body = []
        for idx, stmt in enumerate(node.body):
            if idx == 0 and _is_docstring_expr(stmt):
                new_body.append(stmt)
            else:
                res = self.visit(stmt)
                if isinstance(res, list):
                    new_body.extend(res)
                elif res is not None:
                    new_body.append(res)
        node.body = new_body
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        if _is_overload_def(node):
            return node
        for d_idx, d in enumerate(list(node.decorator_list)):
            if self.current_index == self.target_index:
                lineno = getattr(d, 'lineno', getattr(node, 'lineno', 1))
                dec_name = getattr(d, 'id', getattr(getattr(d, 'func', None), 'id', 'decorator'))
                self.applied_info = (lineno, f"Remove async function decorator @{dec_name}", f"@{dec_name}", "", None, None)
                node.decorator_list = [dec for i, dec in enumerate(node.decorator_list) if i != d_idx]
                self.current_index += 1
                break
            self.current_index += 1
        node.args.defaults = [self.visit(d) if d else None for d in node.args.defaults]
        node.args.kw_defaults = [self.visit(d) if d else None for d in node.args.kw_defaults]
        new_body = []
        for idx, stmt in enumerate(node.body):
            if idx == 0 and _is_docstring_expr(stmt):
                new_body.append(stmt)
            else:
                res = self.visit(stmt)
                if isinstance(res, list):
                    new_body.extend(res)
                elif res is not None:
                    new_body.append(res)
        node.body = new_body
        return node

    def visit_With(self, node: ast.With) -> Any:
        if all(item.optional_vars is None for item in node.items):
            if self.current_index == self.target_index:
                lineno = getattr(node, 'lineno', 1)
                self.applied_info = (lineno, "Bypass context manager (execute inner block without context)", "with ctx:", "bare body", None, None)
                self.current_index += 1
                return [self.visit(stmt) for stmt in node.body]
            self.current_index += 1
        new_body = []
        for stmt in node.body:
            res = self.visit(stmt)
            if isinstance(res, list):
                new_body.extend(res)
            elif res is not None:
                new_body.append(res)
        node.body = new_body
        return node

    def visit_AsyncWith(self, node: ast.AsyncWith) -> Any:
        if all(item.optional_vars is None for item in node.items):
            if self.current_index == self.target_index:
                lineno = getattr(node, 'lineno', 1)
                self.applied_info = (lineno, "Bypass async context manager (execute inner block without context)", "async with ctx:", "bare body", None, None)
                self.current_index += 1
                return [self.visit(stmt) for stmt in node.body]
            self.current_index += 1
        new_body = []
        for stmt in node.body:
            res = self.visit(stmt)
            if isinstance(res, list):
                new_body.extend(res)
            elif res is not None:
                new_body.append(res)
        node.body = new_body
        return node

    def visit_If(self, node: ast.If) -> ast.AST:
        if _is_type_checking_guard(node):
            return node
        return self.generic_visit(node)

    def visit_For(self, node: ast.For) -> ast.AST:
        if not (isinstance(node.iter, ast.List) and len(node.iter.elts) == 0):
            if self.current_index == self.target_index:
                lineno = getattr(node, 'lineno', 1)
                self.applied_info = (lineno, "Empty for-loop iterator (Zero-Iteration Loop)", "for ... in iter:", "for ... in []:", None, None)
                node.iter = ast.List(elts=[], ctx=ast.Load())
                self.current_index += 1
                return node
            self.current_index += 1
        return self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> ast.AST:
        if not (isinstance(node.iter, ast.List) and len(node.iter.elts) == 0):
            if self.current_index == self.target_index:
                lineno = getattr(node, 'lineno', 1)
                self.applied_info = (lineno, "Empty async for-loop iterator (Zero-Iteration Loop)", "async for ... in iter:", "async for ... in []:", None, None)
                node.iter = ast.List(elts=[], ctx=ast.Load())
                self.current_index += 1
                return node
            self.current_index += 1
        return self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> ast.AST:
        if isinstance(node.type, ast.Name) and node.type.id in EXCEPT_MAP:
            if self.current_index == self.target_index:
                lineno = getattr(node, 'lineno', 1)
                old_exc = node.type.id
                new_exc = EXCEPT_MAP[old_exc]
                self.applied_info = (lineno, f"Replace exception catch type '{old_exc}' with '{new_exc}'", old_exc, new_exc, None, None)
                node.type = ast.Name(id=new_exc, ctx=ast.Load())
                self.current_index += 1
                return node
            self.current_index += 1
        return self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST:
        node_target = getattr(node, 'target', None)
        if node_target:
            node.target = self.visit(node_target)
        if node.value:
            node.value = self.visit(node.value)
        return node

    def visit_arg(self, node: ast.arg) -> ast.AST:
        return node

    def visit_Await(self, node: ast.Await) -> ast.AST:
        if self.current_index == self.target_index:
            lineno = getattr(node, 'lineno', 1)
            self.applied_info = (lineno, "Drop await expression (coroutine left unawaited)", "await", "", None, None)
            self.current_index += 1
            return self.visit(node.value)
        self.current_index += 1
        return self.generic_visit(node)

    def visit_Break(self, node: ast.Break) -> ast.AST:
        if self.current_index == self.target_index:
            lineno = getattr(node, 'lineno', 1)
            self.applied_info = (lineno, "Replace 'break' loop control with 'continue'", "break", "continue", None, None)
            self.current_index += 1
            return ast.copy_location(ast.Continue(), node)
        self.current_index += 1
        return node

    def visit_Continue(self, node: ast.Continue) -> ast.AST:
        if self.current_index == self.target_index:
            lineno = getattr(node, 'lineno', 1)
            self.applied_info = (lineno, "Replace 'continue' loop control with 'break'", "continue", "break", None, None)
            self.current_index += 1
            return ast.copy_location(ast.Break(), node)
        self.current_index += 1
        return node

    def visit_Call(self, node: ast.Call) -> ast.AST:
        if is_log_or_print_call(node):
            return node
        if isinstance(node.func, ast.Attribute) and node.func.attr in STRING_METHOD_SWAP:
            if self.current_index == self.target_index:
                lineno = getattr(node, 'lineno', 1)
                old_m = node.func.attr
                new_m = STRING_METHOD_SWAP[old_m]
                self.applied_info = (lineno, f"Swap string method '{old_m}' with '{new_m}'", old_m, new_m, None, None)
                node.func.attr = new_m
                self.current_index += 1
                return node
            self.current_index += 1
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "get" and len(node.args) == 2 and not _is_none_constant(node.args[1]):
            if self.current_index == self.target_index:
                lineno = getattr(node, 'lineno', 1)
                self.applied_info = (lineno, "Remove dictionary .get() default fallback (replace with None)", "get(k, default)", "get(k, None)", None, None)
                node.args[1] = ast.Constant(value=None)
                self.current_index += 1
                return node
            self.current_index += 1
        elif len(node.args) == 2 and not _is_special_builtin_call(node):
            if self.current_index == self.target_index:
                lineno = getattr(node, 'lineno', 1)
                self.applied_info = (lineno, "Swap 2 positional arguments in function call", "func(a, b)", "func(b, a)", None, None)
                node.args = [node.args[1], node.args[0]]
                self.current_index += 1
                return node
            self.current_index += 1
        return self.generic_visit(node)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        self.generic_visit(node)
        op_type = type(node.op)
        if op_type in UNARYOP_MAP:
            if self.current_index == self.target_index:
                new_cls, old_s, new_s = UNARYOP_MAP[op_type]
                node.op = new_cls()
                lineno = getattr(node, 'lineno', 1)
                self.applied_info = (lineno, f"Replace unary operator '{old_s}' with '{new_s}'", old_s, new_s, None, None)
            self.current_index += 1
        elif isinstance(node.op, ast.Not):
            if self.current_index == self.target_index:
                lineno = getattr(node, 'lineno', 1)
                self.applied_info = (lineno, "Remove 'not' logical inversion", "not x", "x", None, None)
                self.current_index += 1
                return node.operand
            self.current_index += 1
        elif isinstance(node.op, ast.Invert):
            if self.current_index == self.target_index:
                lineno = getattr(node, 'lineno', 1)
                self.applied_info = (lineno, "Remove '~' bitwise inversion", "~x", "x", None, None)
                self.current_index += 1
                return node.operand
            self.current_index += 1
        return node

    def visit_Return(self, node: ast.Return) -> ast.AST:
        if not _is_none_constant(node.value):
            if self.current_index == self.target_index:
                lineno = getattr(node, 'lineno', 1)
                self.applied_info = (lineno, "Replace return value with None (statement mutation)", "return", "return None", None, None)
                node.value = ast.Constant(value=None)
                self.current_index += 1
                return node
            self.current_index += 1
            node.value = self.visit(node.value)
        return node

    def visit_Assert(self, node: ast.Assert) -> ast.AST:
        if self.current_index == self.target_index:
            lineno = getattr(node, 'lineno', 1)
            self.applied_info = (lineno, "Delete assert statement / replace with pass", "assert", "pass", None, None)
            self.current_index += 1
            return ast.copy_location(ast.Pass(), node)
        self.current_index += 1
        return self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> ast.AST:
        if isinstance(node.value, ast.Call) and not is_log_or_print_call(node.value):
            if self.current_index == self.target_index:
                lineno = getattr(node, 'lineno', 1)
                self.applied_info = (lineno, "Delete side-effect call statement / replace with pass", "call", "pass", None, None)
                self.current_index += 1
                return ast.copy_location(ast.Pass(), node)
            self.current_index += 1
        return self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> ast.AST:
        if self.current_index == self.target_index:
            lineno = getattr(node, 'lineno', 1)
            self.applied_info = (lineno, "Delete raise statement / replace with pass", "raise", "pass", None, None)
            self.current_index += 1
            return ast.copy_location(ast.Pass(), node)
        self.current_index += 1
        if isinstance(node.exc, ast.Call):
            new_args = []
            for arg in node.exc.args:
                if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)) and (not (isinstance(arg, ast.BinOp) and isinstance(arg.op, (ast.Add, ast.Mod)))):
                    new_args.append(self.visit(arg))
                else:
                    new_args.append(arg)
            node.exc.args = new_args
            if node.cause:
                node.cause = self.visit(node.cause)
            return node
        return self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        new_ops = list(node.ops)
        for i, op in enumerate(node.ops):
            op_type = type(op)
            if op_type in COMPARE_MAP:
                if self.current_index == self.target_index:
                    new_cls, old_s, new_s = COMPARE_MAP[op_type]
                    new_ops[i] = new_cls()
                    lineno = getattr(node, 'lineno', 1)
                    left_node = node.left if i == 0 else node.comparators[i - 1]
                    right_node = node.comparators[i]
                    col_offset = getattr(left_node, 'end_col_offset', None)
                    end_col_offset = getattr(right_node, 'col_offset', None)
                    self.applied_info = (lineno, f"Replace comparison '{old_s}' with '{new_s}'", old_s, new_s, col_offset, end_col_offset)
                self.current_index += 1
        node.ops = new_ops
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        op_type = type(node.op)
        if op_type in BINOP_MAP:
            if self.current_index == self.target_index:
                new_cls, old_s, new_s = BINOP_MAP[op_type]
                node.op = new_cls()
                lineno = getattr(node, 'lineno', 1)
                col_offset = getattr(node.left, 'end_col_offset', None)
                end_col_offset = getattr(node.right, 'col_offset', None)
                self.applied_info = (lineno, f"Replace binary operator '{old_s}' with '{new_s}'", old_s, new_s, col_offset, end_col_offset)
            self.current_index += 1
        return node

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        self.generic_visit(node)
        op_type = type(node.op)
        if op_type in BOOLOP_MAP:
            if self.current_index == self.target_index:
                new_cls, old_s, new_s = BOOLOP_MAP[op_type]
                node.op = new_cls()
                lineno = getattr(node, 'lineno', 1)
                col_offset = getattr(node.values[0], 'end_col_offset', None) if node.values else None
                end_col_offset = getattr(node.values[1], 'col_offset', None) if len(node.values) > 1 else None
                self.applied_info = (lineno, f"Replace logical operator '{old_s}' with '{new_s}'", old_s, new_s, col_offset, end_col_offset)
            self.current_index += 1
        return node

    def visit_AugAssign(self, node: ast.AugAssign) -> ast.AST:
        self.generic_visit(node)
        op_type = type(node.op)
        if op_type in AUGASSIGN_MAP:
            if self.current_index == self.target_index:
                new_cls, old_s, new_s = AUGASSIGN_MAP[op_type]
                node.op = new_cls()
                lineno = getattr(node, 'lineno', 1)
                col_offset = getattr(node.target, 'end_col_offset', None)
                end_col_offset = getattr(node.value, 'col_offset', None)
                self.applied_info = (lineno, f"Replace augmented assignment '{old_s}' with '{new_s}'", old_s, new_s, col_offset, end_col_offset)
            self.current_index += 1
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        self.generic_visit(node)
        lineno = getattr(node, 'lineno', 1)
        col_offset = getattr(node, 'col_offset', None)
        end_col_offset = getattr(node, 'end_col_offset', None)
        if isinstance(node.value, bool):
            if self.current_index == self.target_index:
                old_val = node.value
                node.value = not node.value
                self.applied_info = (lineno, f"Replace boolean literal '{old_val}' with '{node.value}'", str(old_val), str(node.value), col_offset, end_col_offset)
            self.current_index += 1
        elif isinstance(node.value, (int, float)) and (not isinstance(node.value, bool)):
            if self.current_index == self.target_index:
                old_num = node.value
                new_num = old_num + 1 if old_num != 0 else 1
                node.value = new_num
                self.applied_info = (lineno, f"Replace numeric constant '{old_num}' with '{new_num}'", str(old_num), str(new_num), col_offset, end_col_offset)
            self.current_index += 1
        elif isinstance(node.value, str) and not _is_docstring_or_directive(node):
            if self.current_index == self.target_index:
                old_str = node.value
                new_str = f"XX{old_str}XX" if old_str else "XX"
                node.value = new_str
                self.applied_info = (lineno, f"Mutate string literal '{old_str[:15]}' to '{new_str[:15]}'", old_str, new_str, col_offset, end_col_offset)
            self.current_index += 1
        return node

    def visit_Lambda(self, node: ast.Lambda) -> ast.AST:
        if self.current_index == self.target_index:
            lineno = getattr(node, 'lineno', 1)
            if _is_none_constant(node.body):
                self.applied_info = (lineno, "Mutate lambda body from 'None' to '0'", "None", "0", None, None)
                node.body = ast.Constant(value=0)
            else:
                self.applied_info = (lineno, "Mutate lambda body to return 'None'", "body", "None", None, None)
                node.body = ast.Constant(value=None)
            self.current_index += 1
            return node
        self.current_index += 1
        return self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id == "deepcopy":
            if self.current_index == self.target_index:
                lineno = getattr(node, 'lineno', 1)
                self.applied_info = (lineno, "Replace 'deepcopy' with shallow 'copy'", "deepcopy", "copy", None, None)
                node.id = "copy"
                self.current_index += 1
                return node
            self.current_index += 1
        return node

    def visit_IfExp(self, node: ast.IfExp) -> ast.AST:
        if self.current_index == self.target_index:
            lineno = getattr(node, 'lineno', 1)
            self.applied_info = (lineno, "Swap ternary if-else branches", "a if cond else b", "b if cond else a", None, None)
            node.body, node.orelse = node.orelse, node.body
            self.current_index += 1
            return node
        self.current_index += 1
        return self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> ast.AST:
        if node.ifs:
            for if_idx, if_expr in enumerate(list(node.ifs)):
                if self.current_index == self.target_index:
                    lineno = getattr(if_expr, 'lineno', 1)
                    self.applied_info = (lineno, "Invert comprehension 'if' filter condition", "if cond", "if not (cond)", None, None)
                    node.ifs[if_idx] = ast.UnaryOp(op=ast.Not(), operand=if_expr)
                    self.current_index += 1
                    return node
                self.current_index += 1
        return self.generic_visit(node)

    def visit_Yield(self, node: ast.Yield) -> ast.AST:
        if node.value and not _is_none_constant(node.value):
            if self.current_index == self.target_index:
                lineno = getattr(node, 'lineno', 1)
                self.applied_info = (lineno, "Mutate yield expression to 'yield None'", "yield expr", "yield None", None, None)
                node.value = ast.Constant(value=None)
                self.current_index += 1
                return node
            self.current_index += 1
            node.value = self.visit(node.value)
            return node
        elif not node.value:
            if self.current_index == self.target_index:
                lineno = getattr(node, 'lineno', 1)
                self.applied_info = (lineno, "Mutate bare yield to 'yield 0'", "yield", "yield 0", None, None)
                node.value = ast.Constant(value=0)
                self.current_index += 1
                return node
            self.current_index += 1
            return node
        return self.generic_visit(node)

    def visit_YieldFrom(self, node: ast.YieldFrom) -> ast.AST:
        if self.current_index == self.target_index:
            lineno = getattr(node, 'lineno', 1)
            self.applied_info = (lineno, "Replace 'yield from' iterator with empty list", "yield from expr", "yield from []", None, None)
            node.value = ast.List(elts=[], ctx=ast.Load())
            self.current_index += 1
            return node
        self.current_index += 1
        return self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> ast.AST:
        if len(node.cases) > 1:
            for c_idx in range(len(node.cases)):
                if self.current_index == self.target_index:
                    lineno = getattr(node, 'lineno', 1)
                    self.applied_info = (lineno, "Drop pattern matching branch case", "case ...:", "/* dropped case */", None, None)
                    node.cases = [c for i, c in enumerate(node.cases) if i != c_idx]
                    self.current_index += 1
                    return node
                self.current_index += 1
        for case in node.cases:
            if case.guard:
                if self.current_index == self.target_index:
                    lineno = getattr(case, 'lineno', 1)
                    self.applied_info = (lineno, "Invert pattern matching case guard condition", "if guard", "if not (guard)", None, None)
                    case.guard = ast.UnaryOp(op=ast.Not(), operand=case.guard)
                    self.current_index += 1
                    return node
                self.current_index += 1
        return self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> ast.AST:
        return self.generic_visit(node)

def parse_pytest_summary(output: str) -> Dict[str, Any]:
    """
    Parse pytest stdout/stderr to inspect whether any tests actually executed.
    
    Returns a dict with test counts and boolean no_tests_ran.
    """
    lowered = output.lower()
    if 'no tests ran' in lowered or 'no test was collected' in lowered or '0 selected' in lowered:
        return {'passed': 0, 'failed': 0, 'errors': 0, 'total': 0, 'no_tests_ran': True}
    passed_m = re.search('(\\d+)\\s+passed', output)
    failed_m = re.search('(\\d+)\\s+failed', output)
    errors_m = re.search('(\\d+)\\s+error', output)
    passed = int(passed_m.group(1)) if passed_m else 0
    failed = int(failed_m.group(1)) if failed_m else 0
    errors = int(errors_m.group(1)) if errors_m else 0
    total = passed + failed
    no_tests = total == 0 and errors == 0
    return {'passed': passed, 'failed': failed, 'errors': errors, 'total': total, 'no_tests_ran': no_tests}

def extract_collection_error(output: str, returncode: int) -> str:
    """Extract a concise and informative error message from pytest collection / startup failure."""
    out_lower = output.lower()
    if "no module named 'pytest'" in out_lower or "no module named pytest" in out_lower:
        return "Pytest is not installed in the active Python environment (install with: pip install pytest)"

    lines = [line.strip() for line in output.splitlines() if line.strip()]
    err_msgs: List[str] = []
    for line in lines:
        if line.startswith('E   ') or line.startswith('E:'):
            err_msgs.append(line[5:].strip())
        elif any((err in line for err in ['ModuleNotFoundError:', 'ImportError:', 'SyntaxError:', 'NameError:', 'AttributeError:', 'ZoneInfoNotFoundError:', 'SystemError:'])):
            if not line.startswith('WARNING') and (not line.startswith('Notice')) and (not line.startswith('=')):
                err_msgs.append(line)
        elif 'Error while loading conftest' in line or 'ImportError while loading conftest' in line:
            err_msgs.append(line)
    if err_msgs:
        deduped: List[str] = []
        for msg in err_msgs:
            if msg not in deduped:
                deduped.append(msg)
        return ' | '.join(deduped[:3])
    for line in lines:
        if not line.startswith('=') and (not line.startswith('!')) and (not line.startswith('platform')) and (not line.startswith('rootdir')) and (not line.startswith('plugins')):
            if 'error' in line.lower():
                err_msgs.append(line)
    if err_msgs:
        return ' | '.join(err_msgs[:2])
    if lines:
        return lines[-1]
    return f'Pytest exited with return code {returncode}'


def _error_traces_to_mutant(output: str, mutant: Mutant) -> bool:
    """
    Determine if a pytest error or traceback specifically references the mutated file or code path.
    Returns True if the mutated filename/stem is referenced in the traceback/call stack.
    Returns False if the error is an unanchored, generic, or unrelated environment crash.
    """
    fname = mutant.file_path.name
    fstem = mutant.file_path.stem
    for line in output.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue
        if fname in line_clean or f"\\{fname}" in line_clean or f"/{fname}" in line_clean:
            return True
        # Also check if the module stem is part of traceback frame import or definition
        if fstem in line_clean and any(marker in line_clean for marker in ['File "', '.py:', '.py", line', '>>>', 'E   ', 'ERROR', 'setup of']):
            return True
    return False


def collect_skipped_constructs_for_file(file_path: Path, line_ranges: Optional[Set[int]] = None) -> List[SkippedConstruct]:
    """Identify unsupported constructs in a file that Tier 1 skips."""
    try:
        source = file_path.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    collector = SkippedConstructCollector(file_path, source.splitlines())
    collector.visit(tree)
    if line_ranges is not None:
        return [s for s in collector.skipped if s.line_number in line_ranges]
    return collector.skipped

def generate_mutants_for_file(file_path: Path, line_ranges: Optional[Set[int]] = None) -> List[Mutant]:
    """Generate deterministic mutants for a single Python file, optionally filtered to line_ranges."""
    try:
        source = file_path.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = source.splitlines()

    # Collect pragma-suppressed lines (# pragma: no mutate, # mutmut: disable, etc.)
    pragma_suppressed_lines: Set[int] = set()
    for l_idx, line_str in enumerate(lines, start=1):
        if '#' in line_str:
            comment_part = line_str.split('#', 1)[1].lower()
            if any(p in comment_part for p in ['pragma: no mutate', 'pragma: no-mutate', 'mutmut: disable', 'cosmic-ray: disable']):
                pragma_suppressed_lines.add(l_idx)

    finder = DeadCodeFinder()
    finder.visit(tree)
    dead_lines = finder.dead_lines

    counter = MutationCounter()
    counter.visit(tree)
    total_locations = counter.count
    mutants: List[Mutant] = []
    for idx in range(total_locations):
        fresh_tree = ast.parse(source)
        transformer = MutationTransformer(idx)
        mutated_tree = transformer.visit(fresh_tree)
        ast.fix_missing_locations(mutated_tree)
        try:
            mutated_source = ast.unparse(mutated_tree)
        except Exception:
            continue
        lineno = transformer.applied_info[0] if transformer.applied_info else 1
        if lineno in pragma_suppressed_lines or lineno in dead_lines:
            continue
        if line_ranges is not None and lineno not in line_ranges:
            continue
        desc = transformer.applied_info[1] if transformer.applied_info else f'Mutation #{idx + 1}'
        old_val = transformer.applied_info[2] if transformer.applied_info and len(transformer.applied_info) > 2 else ''
        new_val = transformer.applied_info[3] if transformer.applied_info and len(transformer.applied_info) > 3 else ''
        col_offset = transformer.applied_info[4] if transformer.applied_info and len(transformer.applied_info) > 4 else None
        end_col_offset = transformer.applied_info[5] if transformer.applied_info and len(transformer.applied_info) > 5 else None
        raw_line = lines[lineno - 1] if 0 <= lineno - 1 < len(lines) else ''
        orig_line = raw_line.strip()
        if desc.startswith("Replace return value with None"):
            if "return" in orig_line:
                mut_line = re.sub(r"\breturn\b\s+.*", "return None", orig_line)
            else:
                mut_line = "return None"
        elif col_offset is not None and end_col_offset is not None and (0 <= col_offset <= end_col_offset <= len(raw_line)):
            span_text = raw_line[col_offset:end_col_offset]
            if old_val and span_text == old_val:
                mut_line = (raw_line[:col_offset] + new_val + raw_line[end_col_offset:]).strip()
            elif old_val and old_val in span_text:
                mut_span = span_text.replace(old_val, new_val, 1)
                mut_line = (raw_line[:col_offset] + mut_span + raw_line[end_col_offset:]).strip()
            else:
                idx_in_line = raw_line.find(old_val, col_offset)
                if idx_in_line != -1:
                    mut_line = (raw_line[:idx_in_line] + new_val + raw_line[idx_in_line + len(old_val):]).strip()
                else:
                    mut_line = orig_line
        else:
            mut_line = orig_line

        if mut_line == orig_line and old_val and old_val in orig_line:
            if old_val.isalpha():
                mut_line = re.sub(r"\b" + re.escape(old_val) + r"\b", new_val, orig_line, count=1).strip()
            else:
                mut_line = orig_line.replace(old_val, new_val, 1).strip()
        mutant_id = f'{file_path.name}:{lineno}:mutant_{idx + 1}'
        mutants.append(Mutant(mutant_id=mutant_id, file_path=file_path, line_number=lineno, description=desc, original_line=orig_line, mutated_line=mut_line, mutated_source=mutated_source))
    return mutants


class MutationSchemataTransformer(ast.NodeTransformer):
    """
    Transforms a Python AST into an in-memory mutant schemata module where each mutant
    is conditioned on a dynamic runtime switch `_dp_m(switch_idx)`.
    """
    def __init__(
        self,
        pragma_suppressed_lines: Set[int],
        dead_lines: Optional[Set[int]] = None,
        line_ranges: Optional[Set[int]] = None,
    ) -> None:
        self.pragma_suppressed = pragma_suppressed_lines
        self.dead_lines = dead_lines or set()
        self.line_ranges = line_ranges
        self.current_switch = 0
        self.mutant_records: List[Tuple[int, int, str, str, str, Optional[int], Optional[int]]] = []

    def _dp_check(self, mid: int) -> ast.Call:
        return ast.Call(
            func=ast.Name(id="_dp_m", ctx=ast.Load()),
            args=[ast.Constant(value=mid)],
            keywords=[],
        )

    def _wrap_ifexp(
        self,
        original_node: ast.expr,
        mutated_node: ast.expr,
        lineno: int,
        desc: str,
        old_val: str,
        new_val: str,
        col_offset: Optional[int] = None,
        end_col_offset: Optional[int] = None,
    ) -> ast.expr:
        if lineno in self.pragma_suppressed or lineno in self.dead_lines or (self.line_ranges is not None and lineno not in self.line_ranges):
            return original_node
        self.current_switch += 1
        mid = self.current_switch
        self.mutant_records.append((mid, lineno, desc, old_val, new_val, col_offset, end_col_offset))
        return ast.IfExp(
            test=self._dp_check(mid),
            body=mutated_node,
            orelse=original_node,
        )

    def visit_JoinedStr(self, node: ast.JoinedStr) -> ast.AST:
        # FormattedValue expressions inside f-strings can be mutated,
        # but Constant fragments inside JoinedStr.values must not be wrapped in IfExp.
        new_values = []
        for val in node.values:
            if isinstance(val, ast.FormattedValue):
                new_values.append(
                    ast.FormattedValue(
                        value=self.visit(val.value),
                        conversion=val.conversion,
                        format_spec=self.visit(val.format_spec) if val.format_spec else None,
                    )
                )
            else:
                new_values.append(val)
        node.values = new_values
        return node

    def visit_Module(self, node: ast.Module) -> ast.AST:
        new_body = []
        for idx, stmt in enumerate(node.body):
            if idx == 0 and _is_docstring_expr(stmt):
                new_body.append(stmt)
            else:
                new_body.append(self.visit(stmt))
        node.body = new_body
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        node.bases = [self.visit(b) for b in node.bases]
        new_body = []
        for idx, stmt in enumerate(node.body):
            if idx == 0 and _is_docstring_expr(stmt):
                new_body.append(stmt)
            else:
                res = self.visit(stmt)
                if isinstance(res, list):
                    new_body.extend(res)
                elif res is not None:
                    new_body.append(res)
        node.body = new_body
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        if _is_overload_def(node):
            return node
        node.args.defaults = [self.visit(d) if d else None for d in node.args.defaults]
        node.args.kw_defaults = [self.visit(d) if d else None for d in node.args.kw_defaults]
        new_body = []
        for idx, stmt in enumerate(node.body):
            if idx == 0 and _is_docstring_expr(stmt):
                new_body.append(stmt)
            else:
                res = self.visit(stmt)
                if isinstance(res, list):
                    new_body.extend(res)
                elif res is not None:
                    new_body.append(res)
        node.body = new_body
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        if _is_overload_def(node):
            return node
        node.args.defaults = [self.visit(d) if d else None for d in node.args.defaults]
        node.args.kw_defaults = [self.visit(d) if d else None for d in node.args.kw_defaults]
        new_body = []
        for idx, stmt in enumerate(node.body):
            if idx == 0 and _is_docstring_expr(stmt):
                new_body.append(stmt)
            else:
                res = self.visit(stmt)
                if isinstance(res, list):
                    new_body.extend(res)
                elif res is not None:
                    new_body.append(res)
        node.body = new_body
        return node

    def visit_Return(self, node: ast.Return) -> ast.AST:
        if not _is_none_constant(node.value):
            v_val = self.visit(node.value) if node.value is not None else ast.Constant(value=None)
            lineno = getattr(node, "lineno", 1)
            col_offset = getattr(node, "col_offset", None)
            end_col_offset = getattr(node, "end_col_offset", None)
            mut_val = ast.Constant(value=None)
            desc = "Replace return value with None (statement mutation)"
            wrapped_val = self._wrap_ifexp(v_val, mut_val, lineno, desc, "return", "return None", col_offset, end_col_offset)
            return ast.Return(value=wrapped_val)
        return node

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        v_left = self.visit(node.left)
        v_comparators = [self.visit(c) for c in node.comparators]
        orig_compare = ast.Compare(left=v_left, ops=node.ops, comparators=v_comparators)
        if len(node.ops) == 1 and type(node.ops[0]) in COMPARE_MAP:
            lineno = getattr(node, "lineno", 1)
            col_offset = getattr(node, "col_offset", None)
            end_col_offset = getattr(node, "end_col_offset", None)
            mut_op_cls, old_op_str, new_op_str = COMPARE_MAP[type(node.ops[0])]
            mut_compare = ast.Compare(left=v_left, ops=[mut_op_cls()], comparators=v_comparators)
            desc = f"Replace comparison '{old_op_str}' with '{new_op_str}'"
            return self._wrap_ifexp(orig_compare, mut_compare, lineno, desc, old_op_str, new_op_str, col_offset, end_col_offset)
        return orig_compare

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        v_left = self.visit(node.left)
        v_right = self.visit(node.right)
        orig_binop = ast.BinOp(left=v_left, op=node.op, right=v_right)
        if type(node.op) in BINOP_MAP and not is_algebraic_zero_identity(node):
            lineno = getattr(node, "lineno", 1)
            col_offset = getattr(node, "col_offset", None)
            end_col_offset = getattr(node, "end_col_offset", None)
            mut_op_cls, old_op_str, new_op_str = BINOP_MAP[type(node.op)]
            mut_binop = ast.BinOp(left=v_left, op=mut_op_cls(), right=v_right)
            desc = f"Replace binary operator '{old_op_str}' with '{new_op_str}'"
            return self._wrap_ifexp(orig_binop, mut_binop, lineno, desc, old_op_str, new_op_str, col_offset, end_col_offset)
        return orig_binop

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        v_values = [self.visit(v) for v in node.values]
        orig_boolop = ast.BoolOp(op=node.op, values=v_values)
        if type(node.op) in BOOLOP_MAP:
            lineno = getattr(node, "lineno", 1)
            col_offset = getattr(node, "col_offset", None)
            end_col_offset = getattr(node, "end_col_offset", None)
            mut_op_cls, old_op_str, new_op_str = BOOLOP_MAP[type(node.op)]
            mut_boolop = ast.BoolOp(op=mut_op_cls(), values=v_values)
            desc = f"Replace logical operator '{old_op_str}' with '{new_op_str}'"
            return self._wrap_ifexp(orig_boolop, mut_boolop, lineno, desc, old_op_str, new_op_str, col_offset, end_col_offset)
        return orig_boolop

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        v_operand = self.visit(node.operand)
        lineno = getattr(node, "lineno", 1)
        col_offset = getattr(node, "col_offset", None)
        end_col_offset = getattr(node, "end_col_offset", None)
        orig_unary = ast.UnaryOp(op=node.op, operand=v_operand)
        if isinstance(node.op, ast.Not):
            desc = "Invert boolean negation (remove 'not')"
            return self._wrap_ifexp(orig_unary, v_operand, lineno, desc, "not", "", col_offset, end_col_offset)
        elif type(node.op) in UNARYOP_MAP:
            mut_op_cls, old_op_str, new_op_str = UNARYOP_MAP[type(node.op)]
            mut_unary = ast.UnaryOp(op=mut_op_cls(), operand=v_operand)
            desc = f"Replace unary operator '{old_op_str}' with '{new_op_str}'"
            return self._wrap_ifexp(orig_unary, mut_unary, lineno, desc, old_op_str, new_op_str, col_offset, end_col_offset)
        return orig_unary

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        lineno = getattr(node, "lineno", 1)
        col_offset = getattr(node, "col_offset", None)
        end_col_offset = getattr(node, "end_col_offset", None)
        if isinstance(node.value, bool):
            old_val = node.value
            new_val = not node.value
            mut_node = ast.Constant(value=new_val)
            desc = f"Replace boolean literal '{old_val}' with '{new_val}'"
            return self._wrap_ifexp(node, mut_node, lineno, desc, str(old_val), str(new_val), col_offset, end_col_offset)
        elif isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            old_num = node.value
            new_num = old_num + 1 if old_num != 0 else 1
            mut_node = ast.Constant(value=new_num)
            desc = f"Replace numeric constant '{old_num}' with '{new_num}'"
            return self._wrap_ifexp(node, mut_node, lineno, desc, str(old_num), str(new_num), col_offset, end_col_offset)
        elif isinstance(node.value, str) and not _is_docstring_or_directive(node):
            old_str = node.value
            new_str = f"XX{old_str}XX" if old_str else "XX"
            mut_node = ast.Constant(value=new_str)
            desc = f"Mutate string literal '{old_str[:15]}' to '{new_str[:15]}'"
            return self._wrap_ifexp(node, mut_node, lineno, desc, old_str, new_str, col_offset, end_col_offset)
        return node

    def visit_Call(self, node: ast.Call) -> ast.AST:
        if is_log_or_print_call(node):
            return node
        lineno = getattr(node, "lineno", 1)
        col_offset = getattr(node, "col_offset", None)
        end_col_offset = getattr(node, "end_col_offset", None)
        v_func = self.visit(node.func)
        v_args = [self.visit(a) for a in node.args]
        v_kws = [ast.keyword(arg=kw.arg, value=self.visit(kw.value)) for kw in node.keywords]
        orig_call = ast.Call(func=v_func, args=v_args, keywords=v_kws)

        if isinstance(node.func, ast.Attribute) and node.func.attr in STRING_METHOD_SWAP:
            old_attr = node.func.attr
            new_attr = STRING_METHOD_SWAP[old_attr]
            mut_func = ast.Attribute(value=v_func.value if isinstance(v_func, ast.Attribute) else self.visit(node.func.value), attr=new_attr, ctx=node.func.ctx)
            mut_call = ast.Call(func=mut_func, args=v_args, keywords=v_kws)
            desc = f"Swap string method '{old_attr}' with '{new_attr}'"
            return self._wrap_ifexp(orig_call, mut_call, lineno, desc, old_attr, new_attr, col_offset, end_col_offset)
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "get" and len(node.args) == 2 and not _is_none_constant(node.args[1]):
            mut_call = ast.Call(func=v_func, args=[v_args[0], ast.Constant(value=None)], keywords=[])
            desc = "Remove dictionary .get() default fallback (replace with None)"
            return self._wrap_ifexp(orig_call, mut_call, lineno, desc, "default", "None", col_offset, end_col_offset)
        elif len(node.args) == 2 and not _is_special_builtin_call(node) and not is_range_zero_start(node):
            mut_call = ast.Call(func=v_func, args=[v_args[1], v_args[0]], keywords=v_kws)
            desc = "Swap positional arguments in function call (arg1 <-> arg2)"
            return self._wrap_ifexp(orig_call, mut_call, lineno, desc, "arg1, arg2", "arg2, arg1", col_offset, end_col_offset)
        return orig_call


def generate_schemata_for_file(
    file_path: Path,
    line_ranges: Optional[Set[int]] = None,
) -> Tuple[Optional[str], List[Mutant], Dict[str, int]]:
    """
    Generate an in-memory mutant schemata file and mapped Mutant instances.
    """
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except Exception:
        return None, [], {}

    lines = source.splitlines()
    pragma_suppressed_lines: Set[int] = set()
    for l_idx, line_str in enumerate(lines, start=1):
        if "#" in line_str:
            comment_part = line_str.split("#", 1)[1].lower()
            if any(p in comment_part for p in ["pragma: no mutate", "pragma: no-mutate", "mutmut: disable", "cosmic-ray: disable"]):
                pragma_suppressed_lines.add(l_idx)

    finder = DeadCodeFinder()
    finder.visit(tree)

    transformer = MutationSchemataTransformer(
        pragma_suppressed_lines,
        dead_lines=finder.dead_lines,
        line_ranges=line_ranges,
    )
    schemata_tree = transformer.visit(tree)
    ast.fix_missing_locations(schemata_tree)

    # Insert _dp_m runtime switch helper after docstring and __future__ imports
    header_ast = ast.parse('''import os as _dp_os
def _dp_m(mid: int) -> bool:
    return _dp_os.environ.get('__DEPLOYPROOF_MUTANT__', '') == str(mid)
''')
    insert_pos = 0
    for idx, stmt in enumerate(schemata_tree.body):
        if idx == 0 and _is_docstring_expr(stmt):
            insert_pos = idx + 1
        elif isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__":
            insert_pos = idx + 1
        else:
            break

    schemata_tree.body = (
        schemata_tree.body[:insert_pos]
        + header_ast.body
        + schemata_tree.body[insert_pos:]
    )
    ast.fix_missing_locations(schemata_tree)

    try:
        schemata_source = ast.unparse(schemata_tree)
    except Exception:
        return None, [], {}

    mutants: List[Mutant] = []
    switch_map: Dict[str, int] = {}

    for mid, lineno, desc, old_val, new_val, col_offset, end_col_offset in transformer.mutant_records:
        raw_line = lines[lineno - 1] if 0 <= lineno - 1 < len(lines) else ""
        orig_line = raw_line.strip()
        if desc.startswith("Replace return value with None"):
            if "return" in orig_line:
                mut_line = re.sub(r"\breturn\b\s+.*", "return None", orig_line)
            else:
                mut_line = "return None"
        elif col_offset is not None and end_col_offset is not None and (0 <= col_offset <= end_col_offset <= len(raw_line)):
            span_text = raw_line[col_offset:end_col_offset]
            if old_val and span_text == old_val:
                mut_line = (raw_line[:col_offset] + new_val + raw_line[end_col_offset:]).strip()
            elif old_val and old_val in span_text:
                mut_span = span_text.replace(old_val, new_val, 1)
                mut_line = (raw_line[:col_offset] + mut_span + raw_line[end_col_offset:]).strip()
            else:
                idx_in_line = raw_line.find(old_val, col_offset)
                if idx_in_line != -1:
                    mut_line = (raw_line[:idx_in_line] + new_val + raw_line[idx_in_line + len(old_val):]).strip()
                else:
                    mut_line = orig_line
        else:
            mut_line = orig_line

        if mut_line == orig_line and old_val and old_val in orig_line:
            if old_val.isalpha():
                mut_line = re.sub(r"\b" + re.escape(old_val) + r"\b", new_val, orig_line, count=1).strip()
            else:
                mut_line = orig_line.replace(old_val, new_val, 1).strip()

        mutant_id = f"{file_path.name}:{lineno}:schemata_{mid}"
        m = Mutant(
            mutant_id=mutant_id,
            file_path=file_path,
            line_number=lineno,
            description=desc,
            original_line=orig_line,
            mutated_line=mut_line,
            mutated_source="",
        )
        mutants.append(m)
        switch_map[mutant_id] = mid

    return schemata_source, mutants, switch_map

def _error_traces_to_mutant(error_output: str, mutant: Mutant) -> bool:
    """
    Check if an error traceback or collection failure explicitly references the mutated file, line, or module.
    """
    if not error_output:
        return False

    file_name = mutant.file_path.name.lower()
    stem = mutant.file_path.stem.lower()
    out_lower = error_output.lower()

    # 1. Exact file name in error output (e.g. "structures.py" or "core.py")
    if file_name in out_lower:
        return True

    # 2. Specific module import error referencing this module (e.g. "no module named 'mymodule'")
    if f"no module named '{stem}'" in out_lower:
        return True
    if f"no module named \"{stem}\"" in out_lower:
        return True
    if "cannot import name" in out_lower and (f"from '{stem}'" in out_lower or f"from \"{stem}\"" in out_lower):
        return True

    return False


def _build_test_import_map(root: Path) -> Dict[str, Set[Path]]:
    """
    Build a reverse import map from imported module names to the test files that import them.
    Scans all pytest test files across the repository.
    """
    tests_dirs = [d for d in [root / 'tests', root / 'test'] if d.is_dir()]
    if not tests_dirs:
        tests_dirs = [root]

    test_files: List[Path] = []
    for t_dir in tests_dirs:
        for p in t_dir.rglob('*.py'):
            if (p.name.startswith('test_') or p.name.endswith('_test.py') or p.name == 'test.py') and p.is_file() and p.name != 'conftest.py':
                test_files.append(p)

    import_to_tests: Dict[str, Set[Path]] = {}

    for tf in test_files:
        try:
            content = tf.read_text(encoding='utf-8', errors='replace')
            tree = ast.parse(content, filename=str(tf))
        except Exception:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name
                    import_to_tests.setdefault(mod, set()).add(tf)
                    parts = mod.split('.')
                    for i in range(1, len(parts)):
                        import_to_tests.setdefault('.'.join(parts[:i]), set()).add(tf)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    mod = node.module
                    import_to_tests.setdefault(mod, set()).add(tf)
                    parts = mod.split('.')
                    for i in range(1, len(parts)):
                        import_to_tests.setdefault('.'.join(parts[:i]), set()).add(tf)
                    for alias in node.names:
                        full = f"{mod}.{alias.name}"
                        import_to_tests.setdefault(full, set()).add(tf)

    return import_to_tests


def discover_target_tests(target_files: List[Path], root: Path) -> List[str]:
    """
    Discover candidate pytest test targets relevant to the target files with tiered precision.
    
    Tier 1 (High Precision):
      - Direct filename stem matches (e.g. test_models.py for models.py, test_utils/ for utils.py).
      - Direct submodule import matches (test files importing pkg.models, pkg.cookies, etc.).
    
    Tier 2 (Fallback):
      - If Tier 1 matches nothing for a file, falls back to top-level package imports (pkg).
      - Sorts test_<pkg>.py / test_main.py first so pytest -x kills mutants rapidly.
    """
    import_map = _build_test_import_map(root)
    matched_test_files: List[str] = []

    tests_dirs = [d for d in [root / "tests", root / "test"] if d.is_dir()]
    if not tests_dirs:
        tests_dirs = [root]

    all_test_files: List[Path] = []
    for t_dir in tests_dirs:
        for p in t_dir.rglob("*.py"):
            if (p.name.startswith("test_") or p.name.endswith("_test.py") or p.name == "test.py") and p.is_file() and p.name != "conftest.py":
                all_test_files.append(p)

    for f in target_files:
        tier1_matched: List[str] = []
        stem = f.stem
        stems = {stem}
        if stem.startswith("_"):
            stems.add(stem.lstrip("_"))
        if stem.endswith("s") and len(stem) > 1:
            stems.add(stem.rstrip("s"))
            if stem.startswith("_"):
                stems.add(stem.lstrip("_").rstrip("s"))
        else:
            stems.add(stem + "s")
            if stem.startswith("_"):
                stems.add(stem.lstrip("_") + "s")

        # 1. Direct Filename Stem Matching (Highest Priority)
        for tf in all_test_files:
            filename = tf.name
            tf_parts = [p.lower() for p in tf.parts]
            is_stem_match = False
            for s in stems:
                if filename in (f"test_{s}.py", f"{s}_test.py", f"test_{s}s.py") or (s.endswith("s") and filename == f"test_{s[:-1]}.py"):
                    is_stem_match = True
                    break
                if f"test_{s}" in tf_parts or f"{s}_test" in tf_parts or s in tf_parts:
                    is_stem_match = True
                    break
            if is_stem_match:
                try:
                    rel_tf = str(tf.relative_to(root))
                except ValueError:
                    rel_tf = str(tf)
                if rel_tf not in tier1_matched:
                    tier1_matched.append(rel_tf)

        # 2. Specific Submodule Import Matching
        try:
            rel = f.relative_to(root)
        except ValueError:
            rel = f

        parts = list(rel.parts)
        if parts and parts[0] == "src":
            parts = parts[1:]

        top_mod = ""
        if parts:
            clean_parts = list(parts)
            if clean_parts[-1].endswith(".py"):
                clean_parts[-1] = clean_parts[-1][:-3]
            if clean_parts[-1] == "__init__":
                clean_parts = clean_parts[:-1]

            if clean_parts:
                top_mod = clean_parts[0]
                specific_mod = ".".join(clean_parts)
                if specific_mod in import_map:
                    for tf in sorted(import_map[specific_mod], key=lambda x: str(x)):
                        try:
                            rel_tf = str(tf.relative_to(root))
                        except ValueError:
                            rel_tf = str(tf)
                        if rel_tf not in tier1_matched:
                            tier1_matched.append(rel_tf)

        # 3. Tier 2 Fallback: If no direct stem or specific submodule imports found
        if not tier1_matched:
            tier2_matched: List[str] = []
            # Check parent directory stem match
            parent_name = f.parent.name
            parent_stems = {parent_name}
            if parent_name.startswith("_"):
                parent_stems.add(parent_name.lstrip("_"))
            for tf in all_test_files:
                filename = tf.name
                for ps in parent_stems:
                    if filename in (f"test_{ps}.py", f"{ps}_test.py"):
                        try:
                            rel_tf = str(tf.relative_to(root))
                        except ValueError:
                            rel_tf = str(tf)
                        if rel_tf not in tier2_matched:
                            tier2_matched.append(rel_tf)

            # Fallback to top-level package imports
            if top_mod and top_mod in import_map:
                for tf in sorted(import_map[top_mod], key=lambda x: str(x)):
                    try:
                        rel_tf = str(tf.relative_to(root))
                    except ValueError:
                        rel_tf = str(tf)
                    if rel_tf not in tier2_matched:
                        tier2_matched.append(rel_tf)

            # Order fallback tests with primary test_<package>.py first
            tier2_matched.sort(key=lambda x: (
                0 if f"test_{top_mod}.py" in x.lower() or f"{top_mod}_test.py" in x.lower() else
                1 if "test_main.py" in x.lower() or "test_core.py" in x.lower() else 2,
                x
            ))
            selected_tests = tier2_matched
        else:
            selected_tests = tier1_matched

        for m in selected_tests:
            if m not in matched_test_files:
                matched_test_files.append(m)

    return matched_test_files


def _cleanup_pyc_in_dir(directory: Path) -> None:
    """Remove bytecode caches and .pyc files in the given directory."""
    pycache = directory / "__pycache__"
    if pycache.is_dir():
        try:
            shutil.rmtree(pycache, ignore_errors=True)
        except Exception:
            pass
    for pyc in directory.glob("*.pyc"):
        try:
            pyc.unlink(missing_ok=True)
        except Exception:
            pass


def _calculate_baseline_timeout(
    pytest_args: List[str],
    root: Path,
    test_runner_timeout: float = 10.0,
) -> float:
    """
    Calculate an adaptive baseline timeout that scales with test file count, total test suite size,
    and coverage instrumentation overhead (crucial for multi-file --full-repo suites).
    """
    base_min = max(60.0, test_runner_timeout * 4.0)
    per_file_allowance = len(pytest_args) * 35.0

    total_test_bytes = 0
    for arg in pytest_args:
        # Strip pytest node specifiers (e.g. tests/test_foo.py::test_bar)
        clean_path_str = arg.split("::")[0]
        test_path = Path(clean_path_str)
        if not test_path.is_absolute():
            test_path = root / test_path
        if test_path.is_file():
            try:
                total_test_bytes += test_path.stat().st_size
            except OSError:
                pass
        elif test_path.is_dir():
            try:
                for p in test_path.glob("**/*.py"):
                    total_test_bytes += p.stat().st_size
            except OSError:
                pass

    total_test_kb = total_test_bytes / 1024.0
    size_allowance = total_test_kb * 2.5

    multi_file_factor = 1.25 if len(pytest_args) > 1 else 1.0
    computed_timeout = max(base_min, per_file_allowance, size_allowance) * multi_file_factor
    return max(60.0, round(computed_timeout, 1))


def _run_single_mutant_in_sandbox(
    temp_base_str: str,
    snapshot_dir_str: str,
    rel_file_path_str: str,
    mutant_id: str,
    line_number: int,
    description: str,
    original_line: str,
    mutated_line: str,
    mutated_source: str,
    pytest_args: List[str],
    baseline_errors: int,
    effective_timeout: float,
    env_pythonpath: str,
    schemata_switch_num: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Execute a single mutant in a PID-isolated worker sandbox directory.
    
    When schemata_switch_num is provided, runs via in-memory mutation switching with zero disk I/O.
    Falls back to isolated on-disk file writes if schemata is unavailable.
    """
    temp_base = Path(temp_base_str)
    snapshot_dir = Path(snapshot_dir_str)
    worker_dir = temp_base / f"worker_{os.getpid()}"

    if not worker_dir.is_dir():
        try:
            shutil.copytree(snapshot_dir, worker_dir)
        except Exception as e:
            return {
                "mutant_id": mutant_id,
                "status": "RUNNER_ERROR",
                "error_msg": f"Failed initializing worker sandbox from snapshot: {e}",
            }

    target_file = worker_dir / rel_file_path_str
    if not target_file.is_file():
        try:
            snapshot_target = snapshot_dir / rel_file_path_str
            if snapshot_target.is_file():
                target_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(snapshot_target, target_file)
            else:
                shutil.copytree(snapshot_dir, worker_dir, dirs_exist_ok=True)
        except Exception:
            pass

    original_code = ""
    if schemata_switch_num is None:
        try:
            original_code = target_file.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {
                "mutant_id": mutant_id,
                "status": "RUNNER_ERROR",
                "error_msg": f"Failed reading source file in sandbox: {e}",
            }

    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["DEPLOYPROOF_WORKER"] = "1"
    if schemata_switch_num is not None:
        env["__DEPLOYPROOF_MUTANT__"] = str(schemata_switch_num)

    paths_to_add = []
    if (worker_dir / "src").is_dir():
        paths_to_add.append(str(worker_dir / "src"))
    paths_to_add.append(str(worker_dir))
    if env_pythonpath:
        paths_to_add.append(env_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(paths_to_add)

    worker_cache = worker_dir / ".pytest_cache"
    worker_tmp = worker_dir / ".pytest_tmp"
    cmd = [
        sys.executable,
        "-B",
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        "-o",
        f"cache_dir={worker_cache}",
        f"--basetemp={worker_tmp}",
    ]
    if baseline_errors == 0:
        cmd.append("-x")
    
    if not pytest_args:
        return {
            "mutant_id": mutant_id,
            "status": "SURVIVED",
            "error_msg": None,
        }

    effective_pytest_args = list(pytest_args)
    is_nodeids = any("::" in arg for arg in effective_pytest_args)
    if not is_nodeids and len(effective_pytest_args) > 15:
        top_dirs = set(Path(p).parts[0] for p in effective_pytest_args if Path(p).parts)
        if top_dirs and all((worker_dir / d).is_dir() for d in top_dirs):
            effective_pytest_args = sorted(list(top_dirs))
        else:
            effective_pytest_args = effective_pytest_args[:15]
    elif is_nodeids and len(effective_pytest_args) > 25:
        effective_pytest_args = effective_pytest_args[:25]
    cmd.extend(effective_pytest_args)

    status = "SURVIVED"
    error_msg = None

    try:
        if schemata_switch_num is None:
            target_file.write_text(mutated_source, encoding="utf-8")

        res = subprocess.run(
            cmd,
            cwd=worker_dir,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=effective_timeout,
        )
        combined_out = res.stdout + "\n" + res.stderr
        mut_summary = parse_pytest_summary(combined_out)
        mut_failed = mut_summary.get("failed", 0)
        mut_passed = mut_summary.get("passed", 0)
        mut_errors = mut_summary.get("errors", 0)

        if res.returncode == 5 or mut_summary["no_tests_ran"]:
            status = "SURVIVED"
        elif mut_failed > 0:
            status = "KILLED"
        elif mut_errors > baseline_errors or (res.returncode == 1 and mut_passed == 0 and mut_failed == 0):
            temp_mutant = Mutant(
                mutant_id=mutant_id,
                file_path=Path(rel_file_path_str),
                line_number=line_number,
                description=description,
                original_line=original_line,
                mutated_line=mutated_line,
                mutated_source=mutated_source,
            )
            if _error_traces_to_mutant(combined_out, temp_mutant):
                status = "KILLED"
            else:
                status = "RUNNER_ERROR"
                concise = extract_collection_error(combined_out, res.returncode)
                error_msg = f"Pytest exit code {res.returncode}: {concise}"
        elif mut_passed > 0 and mut_failed == 0 and mut_errors <= baseline_errors:
            status = "SURVIVED"
        elif res.returncode in (2, 3, 4):
            temp_mutant = Mutant(
                mutant_id=mutant_id,
                file_path=Path(rel_file_path_str),
                line_number=line_number,
                description=description,
                original_line=original_line,
                mutated_line=mutated_line,
                mutated_source=mutated_source,
            )
            if _error_traces_to_mutant(combined_out, temp_mutant):
                status = "KILLED"
            else:
                status = "RUNNER_ERROR"
                concise = extract_collection_error(combined_out, res.returncode)
                error_msg = f"Pytest exit code {res.returncode}: {concise}"
        else:
            status = "SURVIVED"
    except subprocess.TimeoutExpired:
        status = "KILLED"
    except Exception as e:
        status = "RUNNER_ERROR"
        error_msg = f"Execution exception: {type(e).__name__}: {e}"
    finally:
        if schemata_switch_num is None:
            try:
                target_file.write_text(original_code, encoding="utf-8")
                _cleanup_pyc_in_dir(target_file.parent)
            except Exception:
                pass

    return {
        "mutant_id": mutant_id,
        "status": status,
        "error_msg": error_msg,
    }


def _normalize_test_nodeid(nodeid: str, workdir: Path) -> str:
    """Normalize a pytest nodeid (path::test_name) so its file path exists relative to workdir."""
    if "::" in nodeid:
        file_part, test_part = nodeid.split("::", 1)
        suffix = "::" + test_part
    else:
        file_part = nodeid
        suffix = ""

    fp = Path(file_part)
    if (workdir / fp).exists():
        return nodeid

    if fp.is_absolute() and fp.exists():
        try:
            rel = fp.relative_to(workdir).as_posix()
            return f"{rel}{suffix}"
        except ValueError:
            return f"{fp.as_posix()}{suffix}"

    # Search if filename exists in workdir
    for candidate in workdir.rglob(fp.name):
        if candidate.is_file():
            try:
                rel = candidate.relative_to(workdir).as_posix()
                return f"{rel}{suffix}"
            except ValueError:
                pass

    return nodeid


def _run_mutation_tests_sequential(
    target_files: List[Path],
    repo_root: Optional[Path] = None,
    test_runner_timeout: float = 10.0,
    extra_pytest_args: Optional[List[str]] = None,
    is_full_repo: bool = False,
    base: Optional[str] = None,
    quiet: bool = False,
) -> MutationResult:
    """
    Execute targeted sequential mutation testing across target files (diff-scoped mode).
    """
    root = (repo_root or Path.cwd()).resolve()
    start_time = time.time()
    file_mutants_map: Dict[Path, List[Mutant]] = {}
    file_schemata_code_map: Dict[Path, str] = {}
    file_switch_map: Dict[Path, Dict[str, int]] = {}
    all_skipped: List[SkippedConstruct] = []
    all_pruned_equivalent: List[PrunedEquivalentMutant] = []
    total_mutants_count = 0

    for f in target_files:
        if f.is_file() and f.suffix == '.py':
            line_ranges = None
            if not is_full_repo:
                from deployproof.diff import get_modified_line_ranges
                line_ranges = get_modified_line_ranges(f, root, base=base)
            
            schemata_src, f_mutants, switch_map = generate_schemata_for_file(f, line_ranges=line_ranges)
            if schemata_src and f_mutants:
                file_schemata_code_map[f] = schemata_src
                file_switch_map[f] = switch_map
            else:
                f_mutants = generate_mutants_for_file(f, line_ranges=line_ranges)

            file_mutants_map[f] = f_mutants
            total_mutants_count += len(f_mutants)
            all_skipped.extend(collect_skipped_constructs_for_file(f, line_ranges=line_ranges))
            all_pruned_equivalent.extend(collect_equivalent_mutants_for_file(f, line_ranges=line_ranges))

    if total_mutants_count == 0:
        return MutationResult(
            total_mutants=0,
            killed_mutants=0,
            survived_mutants=[],
            untested_files=[],
            runner_errors=[],
            skipped_constructs=all_skipped,
            pruned_equivalent_mutants=all_pruned_equivalent,
            mutation_score=100.0,
            duration_seconds=round(time.time() - start_time, 2),
            files_tested=target_files,
        )

    killed_count = 0
    survived: List[Mutant] = []
    runner_errors: List[Tuple[Mutant, str]] = []
    untested_files_set: Set[Path] = set()
    completed_mutants = 0
    last_progress_print = 0.0

    env = os.environ.copy()
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    current_pythonpath = env.get('PYTHONPATH', '')
    paths_to_add = []
    if (root / 'src').is_dir():
        paths_to_add.append(str(root / 'src'))
    paths_to_add.append(str(root))
    new_pythonpath = os.pathsep.join(paths_to_add)
    if current_pythonpath:
        new_pythonpath = f'{new_pythonpath}{os.pathsep}{current_pythonpath}'
    env['PYTHONPATH'] = new_pythonpath

    global _CURRENT_MUTATED_FILE, _CURRENT_ORIGINAL_CONTENT
    install_mutation_signal_handlers()

    try:
        for f, mutants in file_mutants_map.items():
            if not mutants:
                continue

            if extra_pytest_args:
                pytest_args = list(extra_pytest_args)
            else:
                targeted_tests = discover_target_tests([f], root)
                pytest_args = targeted_tests if targeted_tests else []

            if not pytest_args:
                untested_files_set.add(f)
                for mutant in mutants:
                    mutant.status = 'SURVIVED'
                    survived.append(mutant)
                continue

            has_coverage = importlib.util.find_spec("coverage") is not None
            cov_temp_dir = tempfile.mkdtemp(prefix="deployproof_seq_cov_")
            cov_file = Path(cov_temp_dir) / ".coverage"
            cov_source = str(root / "src") if (root / "src").is_dir() else str(root)

            if has_coverage:
                pytest_cmd = [
                    sys.executable,
                    "-B",
                    "-m",
                    "coverage",
                    "run",
                    f"--data-file={cov_file}",
                    f"--source={cov_source}",
                    "-m",
                    "pytest",
                    "-q",
                    "--tb=short",
                    "-p",
                    "deployproof.coverage_plugin",
                ] + pytest_args
            else:
                pytest_cmd = [sys.executable, "-B", "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider"] + pytest_args

            t0 = time.time()
            baseline_timeout = _calculate_baseline_timeout(pytest_args, root, test_runner_timeout)

            try:
                baseline_res = subprocess.run(
                    pytest_cmd,
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=baseline_timeout,
                )
                if has_coverage and (
                    "no module named coverage" in baseline_res.stderr.lower()
                    or (baseline_res.returncode != 0 and parse_pytest_summary(baseline_res.stdout + "\n" + baseline_res.stderr)["no_tests_ran"])
                ):
                    fallback_cmd = [sys.executable, "-B", "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider"] + pytest_args
                    baseline_res = subprocess.run(
                        fallback_cmd,
                        cwd=root,
                        env=env,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=baseline_timeout,
                    )
            except Exception as e:
                try:
                    shutil.rmtree(cov_temp_dir, ignore_errors=True)
                except Exception:
                    pass
                return MutationResult(
                    total_mutants=total_mutants_count,
                    killed_mutants=killed_count,
                    survived_mutants=survived,
                    untested_files=sorted(untested_files_set),
                    runner_errors=runner_errors,
                    skipped_constructs=all_skipped,
                    mutation_score=None,
                    duration_seconds=round(time.time() - start_time, 2),
                    files_tested=target_files,
                    collection_error=f"Execution exception during baseline test run: {type(e).__name__}: {e}",
                )

            # Load coverage map for current file
            seq_f_contexts: Dict[int, List[str]] = {}
            seq_f_lines: Optional[Set[int]] = None
            if has_coverage and cov_file.is_file():
                try:
                    import coverage
                    cov = coverage.Coverage(data_file=str(cov_file))
                    cov.load()
                    cov_data = cov.get_data()
                    for mf in cov_data.measured_files():
                        if Path(mf).resolve() == f.resolve() or Path(mf).name.lower() == f.name.lower():
                            ctx_map = cov_data.contexts_by_lineno(mf)
                            for l_no, ctx_list in ctx_map.items():
                                valid_tests = [c for c in ctx_list if c and c.strip()]
                                if valid_tests:
                                    seq_f_contexts[l_no] = sorted(list(set(valid_tests)))
                            executed_lines = cov_data.lines(mf)
                            if executed_lines:
                                seq_f_lines = set(executed_lines)
                            break
                except Exception:
                    pass

            try:
                shutil.rmtree(cov_temp_dir, ignore_errors=True)
            except Exception:
                pass

            baseline_duration = max(time.time() - t0, 0.5)
            combined_output = baseline_res.stdout + '\n' + baseline_res.stderr
            baseline_summary = parse_pytest_summary(combined_output)

            is_collection_error = (
                baseline_res.returncode in (2, 3, 4)
                or 'modulenotfounderror' in combined_output.lower()
                or 'importerror' in combined_output.lower()
                or ('error during collection' in combined_output.lower())
                or ('error while loading conftest' in combined_output.lower())
                or ('zoneinfonotfounderror' in combined_output.lower())
                or (
                    baseline_summary.get('errors', 0) > 0
                    and baseline_summary.get('passed', 0) == 0
                    and (baseline_summary.get('failed', 0) == 0)
                )
            )
            if is_collection_error:
                err_msg = extract_collection_error(combined_output, baseline_res.returncode)
                return MutationResult(
                    total_mutants=total_mutants_count,
                    killed_mutants=killed_count,
                    survived_mutants=survived,
                    untested_files=sorted(untested_files_set),
                    runner_errors=runner_errors,
                    skipped_constructs=all_skipped,
                    mutation_score=None,
                    duration_seconds=round(time.time() - start_time, 2),
                    files_tested=target_files,
                    collection_error=err_msg,
                )

            if baseline_res.returncode == 5 or baseline_summary['no_tests_ran']:
                untested_files_set.add(f)
                for mutant in mutants:
                    mutant.status = 'SURVIVED'
                    survived.append(mutant)
                continue

            effective_timeout = max(baseline_duration * 1.5, test_runner_timeout)
            baseline_has_errors = baseline_summary.get('errors', 0) > 0

            original_code = f.read_text(encoding='utf-8', errors='replace')
            _CURRENT_MUTATED_FILE = f
            _CURRENT_ORIGINAL_CONTENT = original_code

            use_schemata = f in file_schemata_code_map
            if use_schemata:
                f.write_text(file_schemata_code_map[f], encoding='utf-8')

            try:
                for mutant in mutants:
                    completed_mutants += 1

                    # Dynamic test selection & instant unexecuted line handling
                    if seq_f_lines is not None:
                        if mutant.line_number not in seq_f_lines:
                            # Zero tests execute this line -> mutant survives instantly without subprocess overhead
                            mutant.status = "SURVIVED"
                            survived.append(mutant)
                            continue

                        covering_tests = seq_f_contexts.get(mutant.line_number, [])
                        if covering_tests:
                            mutant_pytest_args = [_normalize_test_nodeid(t, root) for t in covering_tests[:15]]
                        else:
                            mutant_pytest_args = pytest_args
                    else:
                        mutant_pytest_args = pytest_args

                    mutant_pytest_cmd = [sys.executable, '-B', '-m', 'pytest', '-q', '--tb=short', '-p', 'no:cacheprovider']
                    if not baseline_has_errors:
                        mutant_pytest_cmd.append('-x')
                    mutant_pytest_cmd.extend(mutant_pytest_args)
                    now = time.time()
                    if not quiet and (
                        (completed_mutants == 1)
                        or (completed_mutants % 5 == 0)
                        or (now - last_progress_print >= 5.0)
                        or (completed_mutants == total_mutants_count)
                    ):
                        if (now - last_progress_print >= 0.5) or (completed_mutants == total_mutants_count):
                            last_progress_print = now
                            elapsed = now - start_time
                            elapsed_str = f"{int(elapsed // 60)}m{int(elapsed % 60):02d}s"
                            print(
                                f"  [{completed_mutants}/{total_mutants_count} mutants] elapsed: {elapsed_str}",
                                flush=True,
                            )

                    switch_num = file_switch_map.get(f, {}).get(mutant.mutant_id)
                    mutant_env = env.copy()
                    if switch_num is not None:
                        mutant_env['__DEPLOYPROOF_MUTANT__'] = str(switch_num)
                    else:
                        mutant.file_path.write_text(mutant.mutated_source, encoding='utf-8')

                    try:
                        res = subprocess.run(
                            mutant_pytest_cmd,
                            cwd=root,
                            env=mutant_env,
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            errors='replace',
                            timeout=effective_timeout,
                        )
                        combined_out = res.stdout + '\n' + res.stderr
                        mut_summary = parse_pytest_summary(combined_out)
                        baseline_errors = baseline_summary.get('errors', 0)
                        mut_failed = mut_summary.get('failed', 0)
                        mut_passed = mut_summary.get('passed', 0)
                        mut_errors = mut_summary.get('errors', 0)

                        if res.returncode == 5 or mut_summary['no_tests_ran']:
                            mutant.status = 'SURVIVED'
                            survived.append(mutant)
                        elif mut_failed > 0:
                            mutant.status = 'KILLED'
                            killed_count += 1
                        elif mut_errors > baseline_errors or (res.returncode == 1 and mut_passed == 0 and mut_failed == 0):
                            if _error_traces_to_mutant(combined_out, mutant):
                                mutant.status = 'KILLED'
                                killed_count += 1
                            else:
                                mutant.status = 'RUNNER_ERROR'
                                concise_err = extract_collection_error(combined_out, res.returncode)
                                err_msg = f'Pytest exit code {res.returncode}: {concise_err}'
                                runner_errors.append((mutant, err_msg))
                        elif mut_passed > 0 and mut_failed == 0 and mut_errors <= baseline_errors:
                            mutant.status = 'SURVIVED'
                            survived.append(mutant)
                        elif res.returncode in (2, 3, 4):
                            if _error_traces_to_mutant(combined_out, mutant):
                                mutant.status = 'KILLED'
                                killed_count += 1
                            else:
                                mutant.status = 'RUNNER_ERROR'
                                concise_err = extract_collection_error(combined_out, res.returncode)
                                err_msg = f'Pytest exit code {res.returncode}: {concise_err}'
                                runner_errors.append((mutant, err_msg))
                        else:
                            mutant.status = 'SURVIVED'
                            survived.append(mutant)
                    except subprocess.TimeoutExpired:
                        mutant.status = 'KILLED'
                        killed_count += 1
                    except Exception as e:
                        mutant.status = 'RUNNER_ERROR'
                        runner_errors.append((mutant, f'Execution exception: {type(e).__name__}: {e}'))
                    finally:
                        if switch_num is None:
                            if use_schemata:
                                f.write_text(file_schemata_code_map[f], encoding='utf-8')
                            else:
                                f.write_text(original_code, encoding='utf-8')
            finally:
                f.write_text(original_code, encoding='utf-8')
                _CURRENT_MUTATED_FILE = None
                _CURRENT_ORIGINAL_CONTENT = None
    finally:
        _restore_current_mutant_file()
        remove_mutation_signal_handlers()

    valid_mutants_count = killed_count + len(survived)
    if valid_mutants_count > 0:
        score = killed_count / valid_mutants_count * 100.0
    else:
        score = 0.0 if untested_files_set else 100.0

    return MutationResult(
        total_mutants=total_mutants_count,
        killed_mutants=killed_count,
        survived_mutants=survived,
        untested_files=sorted(untested_files_set),
        runner_errors=runner_errors,
        skipped_constructs=all_skipped,
        pruned_equivalent_mutants=all_pruned_equivalent,
        mutation_score=round(score, 1),
        duration_seconds=round(time.time() - start_time, 2),
        files_tested=target_files,
    )


def run_mutation_tests_parallel(
    target_files: List[Path],
    repo_root: Optional[Path] = None,
    test_runner_timeout: float = 10.0,
    extra_pytest_args: Optional[List[str]] = None,
    workers: Optional[int] = None,
    is_full_repo: bool = False,
    base: Optional[str] = None,
    quiet: bool = False,
) -> MutationResult:
    """
    Execute mutation testing across target files using an isolated multi-worker ProcessPoolExecutor.
    
    Each worker executes in its own isolated filesystem sandbox with live progress tracking.
    """
    root = (repo_root or Path.cwd()).resolve()
    start_time = time.time()

    # 1. Determine worker count (sane cap at 8 by default)
    import multiprocessing
    cpu_count = multiprocessing.cpu_count() or 1
    actual_workers = min(cpu_count, 8) if workers is None else max(1, workers)

    # 2. Collect mutants and skipped constructs
    file_mutants_map: Dict[Path, List[Mutant]] = {}
    file_schemata_code_map: Dict[Path, str] = {}
    file_switch_map: Dict[Path, Dict[str, int]] = {}
    all_skipped: List[SkippedConstruct] = []
    all_pruned_equivalent: List[PrunedEquivalentMutant] = []
    total_mutants_count = 0

    for f in target_files:
        if f.is_file() and f.suffix == '.py':
            line_ranges = None
            if not is_full_repo:
                from deployproof.diff import get_modified_line_ranges
                line_ranges = get_modified_line_ranges(f, root, base=base)
            
            schemata_src, f_mutants, switch_map = generate_schemata_for_file(f, line_ranges=line_ranges)
            if schemata_src and f_mutants:
                file_schemata_code_map[f] = schemata_src
                file_switch_map[f] = switch_map
            else:
                f_mutants = generate_mutants_for_file(f, line_ranges=line_ranges)

            file_mutants_map[f] = f_mutants
            total_mutants_count += len(f_mutants)
            all_skipped.extend(collect_skipped_constructs_for_file(f, line_ranges=line_ranges))
            all_pruned_equivalent.extend(collect_equivalent_mutants_for_file(f, line_ranges=line_ranges))

    if total_mutants_count == 0:
        return MutationResult(
            total_mutants=0,
            killed_mutants=0,
            survived_mutants=[],
            untested_files=[],
            runner_errors=[],
            skipped_constructs=all_skipped,
            pruned_equivalent_mutants=all_pruned_equivalent,
            mutation_score=100.0,
            duration_seconds=round(time.time() - start_time, 2),
            files_tested=target_files,
        )

    # 3. Discover targeted tests per file and identify untested files
    file_test_map: Dict[Path, List[str]] = {}
    untested_files_set: Set[Path] = set()
    tested_files: List[Path] = []

    for f, mutants in file_mutants_map.items():
        if not mutants:
            continue
        if extra_pytest_args:
            pytest_args = list(extra_pytest_args)
        else:
            targeted = discover_target_tests([f], root)
            pytest_args = targeted if targeted else []

        if not pytest_args:
            untested_files_set.add(f)
            for m in mutants:
                m.status = 'SURVIVED'
        else:
            file_test_map[f] = pytest_args
            tested_files.append(f)

    if not tested_files:
        all_survived = [m for mutants in file_mutants_map.values() for m in mutants]
        return MutationResult(
            total_mutants=total_mutants_count,
            killed_mutants=0,
            survived_mutants=all_survived,
            untested_files=sorted(untested_files_set),
            runner_errors=[],
            skipped_constructs=all_skipped,
            pruned_equivalent_mutants=all_pruned_equivalent,
            mutation_score=0.0,
            duration_seconds=round(time.time() - start_time, 2),
            files_tested=target_files,
        )

    # 4. Prepare worker sandboxes in temp directory
    cleanup_stale_deployproof_temp_dirs()
    temp_dir_obj = tempfile.TemporaryDirectory(prefix="deployproof_workers_")
    temp_base = Path(temp_dir_obj.name)
    _ACTIVE_TEMP_DIRS.add(temp_base)
    try:
        (temp_base / f".deployproof_pid_{os.getpid()}").touch()
    except Exception:
        pass

    env_pythonpath = os.environ.get("PYTHONPATH", "")
    from deployproof.diff import resolve_full_repo_session_files
    all_repo_session_files = resolve_full_repo_session_files(cwd=root)

    try:
        if not quiet:
            print(f"DeployProof: Initializing {actual_workers} isolated parallel workers for full repo mutation scan...", flush=True)

        snapshot_dir = temp_base / "snapshot"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        for src_file in all_repo_session_files:
            try:
                rel_p = src_file.relative_to(root)
            except ValueError:
                rel_p = Path(src_file.name)
            dest_p = snapshot_dir / rel_p
            dest_p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest_p)

        # Ensure coverage plugin is copied into snapshot as a standalone module
        # so pytest can load it via -p _deployproof_cov_plugin regardless of package install status
        plugin_src = Path(__file__).resolve().parent / "coverage_plugin.py"
        if plugin_src.is_file():
            shutil.copy2(plugin_src, snapshot_dir / "_deployproof_cov_plugin.py")
            if (snapshot_dir / "src" / "deployproof").is_dir():
                shutil.copy2(plugin_src, snapshot_dir / "src" / "deployproof" / "coverage_plugin.py")

        # 5. Baseline runs for unique test suites with dynamic coverage context recording
        file_baseline_info: Dict[Path, Tuple[int, float]] = {}
        env_snapshot = os.environ.copy()
        env_snapshot["PYTHONDONTWRITEBYTECODE"] = "1"
        env_snapshot["DEPLOYPROOF_WORKER"] = "1"
        paths_to_add = []
        pkg_root = Path(__file__).resolve().parent.parent
        paths_to_add.append(str(pkg_root))
        if (snapshot_dir / "src").is_dir():
            paths_to_add.append(str(snapshot_dir / "src"))
        paths_to_add.append(str(snapshot_dir))
        if env_pythonpath:
            paths_to_add.append(env_pythonpath)
        env_snapshot["PYTHONPATH"] = os.pathsep.join(paths_to_add)

        snapshot_cache = snapshot_dir / ".pytest_cache"
        snapshot_tmp = snapshot_dir / ".pytest_tmp"
        cov_source = str(snapshot_dir / "src") if (snapshot_dir / "src").is_dir() else str(snapshot_dir)

        all_unique_pytest_args = sorted(list(set(t for f in tested_files for t in file_test_map.get(f, []))))
        if not all_unique_pytest_args:
            all_unique_pytest_args = ["tests"] if (snapshot_dir / "tests").is_dir() else [str(snapshot_dir)]

        if not quiet:
            print(f"DeployProof: Running baseline test suite on {len(all_unique_pytest_args)} test file(s) (collecting coverage map)...", flush=True)

        t0 = time.time()
        baseline_timeout = _calculate_baseline_timeout(all_unique_pytest_args, snapshot_dir, test_runner_timeout)
        has_coverage = importlib.util.find_spec("coverage") is not None

        if has_coverage:
            pytest_cmd = [
                sys.executable,
                "-B",
                "-m",
                "coverage",
                "run",
                "-p",
                f"--source={cov_source}",
                "-m",
                "pytest",
                "-q",
                "--tb=short",
                "-p",
                "_deployproof_cov_plugin",
                "-o",
                f"cache_dir={snapshot_cache}",
                f"--basetemp={snapshot_tmp}",
            ] + all_unique_pytest_args
        else:
            pytest_cmd = [
                sys.executable,
                "-B",
                "-m",
                "pytest",
                "-q",
                "--tb=short",
                "-o",
                f"cache_dir={snapshot_cache}",
                f"--basetemp={snapshot_tmp}",
            ] + all_unique_pytest_args

        try:
            baseline_res = subprocess.run(
                pytest_cmd,
                cwd=snapshot_dir,
                env=env_snapshot,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=baseline_timeout,
            )
            # If coverage run failed to execute, fallback to standard pytest
            if has_coverage and (
                "no module named coverage" in baseline_res.stderr.lower()
                or "coverage" in baseline_res.stderr.lower()
                or (baseline_res.returncode != 0 and parse_pytest_summary(baseline_res.stdout + "\n" + baseline_res.stderr)["no_tests_ran"])
            ):
                fallback_cmd = [
                    sys.executable,
                    "-B",
                    "-m",
                    "pytest",
                    "-q",
                    "--tb=short",
                    "-o",
                    f"cache_dir={snapshot_cache}",
                    f"--basetemp={snapshot_tmp}",
                ] + all_unique_pytest_args
                baseline_res = subprocess.run(
                    fallback_cmd,
                    cwd=snapshot_dir,
                    env=env_snapshot,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=baseline_timeout,
                )
        except Exception as e:
            return MutationResult(
                total_mutants=total_mutants_count,
                killed_mutants=0,
                survived_mutants=[],
                untested_files=sorted(untested_files_set),
                runner_errors=[],
                skipped_constructs=all_skipped,
                mutation_score=None,
                duration_seconds=round(time.time() - start_time, 2),
                files_tested=target_files,
                collection_error=f"Execution exception during baseline test run: {type(e).__name__}: {e}",
            )

        baseline_duration = max(time.time() - t0, 0.5)
        if not quiet:
            print(f"DeployProof: Baseline test run completed in {baseline_duration:.1f}s.", flush=True)
        combined_output = baseline_res.stdout + "\n" + baseline_res.stderr
        baseline_summary = parse_pytest_summary(combined_output)

        is_collection_error = (
            baseline_res.returncode in (2, 3, 4)
            or "modulenotfounderror" in combined_output.lower()
            or "importerror" in combined_output.lower()
            or ("error during collection" in combined_output.lower())
            or ("error while loading conftest" in combined_output.lower())
            or ("zoneinfonotfounderror" in combined_output.lower())
            or (
                baseline_summary.get("errors", 0) > 0
                and baseline_summary.get("passed", 0) == 0
                and (baseline_summary.get("failed", 0) == 0)
            )
        )
        if is_collection_error:
            err_msg = extract_collection_error(combined_output, baseline_res.returncode)
            return MutationResult(
                total_mutants=total_mutants_count,
                killed_mutants=0,
                survived_mutants=[],
                untested_files=sorted(untested_files_set),
                runner_errors=[],
                skipped_constructs=all_skipped,
                mutation_score=None,
                duration_seconds=round(time.time() - start_time, 2),
                files_tested=target_files,
                collection_error=err_msg,
            )

        no_tests = (baseline_res.returncode == 5 or baseline_summary["no_tests_ran"])
        eff_timeout = max(baseline_duration * 1.5, test_runner_timeout)
        for f in tested_files:
            if no_tests:
                untested_files_set.add(f)
                for m in file_mutants_map[f]:
                    m.status = 'SURVIVED'
            else:
                file_baseline_info[f] = (baseline_summary.get("errors", 0), eff_timeout)

        # 5b. Extract per-file line-to-test coverage context mapping
        file_line_contexts: Dict[Path, Dict[int, List[str]]] = {}
        file_measured_lines: Dict[Path, Set[int]] = {}
        try:
            import coverage
            cov_file = snapshot_dir / ".coverage"
            cov = coverage.Coverage(data_file=str(cov_file) if cov_file.is_file() else None)
            try:
                cov.combine(data_paths=[str(snapshot_dir)])
            except Exception:
                pass
            cov.load()
            cov_data = cov.get_data()
            for mf in cov_data.measured_files():
                mf_p = Path(mf).resolve()
                try:
                    rel_p = mf_p.relative_to(snapshot_dir.resolve())
                    orig_p = (root / rel_p).resolve()
                except ValueError:
                    orig_p = mf_p

                ctx_map = cov_data.contexts_by_lineno(mf)
                clean_ctx: Dict[int, List[str]] = {}
                for l_no, ctx_list in ctx_map.items():
                    valid_tests = [c for c in ctx_list if c and c.strip()]
                    if valid_tests:
                        clean_ctx[l_no] = sorted(list(set(valid_tests)))
                if clean_ctx:
                    file_line_contexts[orig_p] = clean_ctx
                    file_line_contexts[mf_p] = clean_ctx

                executed_lines = cov_data.lines(mf)
                if executed_lines:
                    file_measured_lines[orig_p] = set(executed_lines)
                    file_measured_lines[mf_p] = set(executed_lines)
        except Exception:
            file_line_contexts = {}
            file_measured_lines = {}

        # 5c. Apply schemata transformations to snapshot directory for worker evaluation
        for src_file, schemata_code in file_schemata_code_map.items():
            try:
                rel_p = src_file.relative_to(root)
            except ValueError:
                rel_p = Path(src_file.name)
            dest_p = snapshot_dir / rel_p
            dest_p.parent.mkdir(parents=True, exist_ok=True)
            dest_p.write_text(schemata_code, encoding="utf-8")

        # 6. Build list of mutant tasks with coverage-guided test selection
        tasks = []
        mutants_by_id: Dict[str, Mutant] = {}
        temp_base_str = str(temp_base)
        snapshot_dir_str = str(snapshot_dir)
        survived: List[Mutant] = []

        for f, mutants in file_mutants_map.items():
            if f in untested_files_set or f not in file_baseline_info:
                continue
            baseline_errors, effective_timeout = file_baseline_info[f]
            default_pytest_args = file_test_map[f]
            try:
                rel_f_str = f.relative_to(root).as_posix()
            except ValueError:
                rel_f_str = f.name

            # Lookup file's coverage contexts and measured lines
            f_contexts = {}
            f_lines = None
            f_resolved = f.resolve()
            for stored_path, ctx_map in file_line_contexts.items():
                if stored_path == f_resolved or str(stored_path).lower() == str(f_resolved).lower() or stored_path.name.lower() == f.name.lower():
                    f_contexts = ctx_map
                    break
            for stored_path, l_set in file_measured_lines.items():
                if stored_path == f_resolved or str(stored_path).lower() == str(f_resolved).lower() or stored_path.name.lower() == f.name.lower():
                    f_lines = l_set
                    break

            for m in mutants:
                mutants_by_id[m.mutant_id] = m

                # Dynamic test selection & instant unexecuted line handling
                if f_lines is not None:
                    # If this line was never executed during baseline test run (0 tests hit it):
                    if m.line_number not in f_lines:
                        # Zero tests execute this line -> mutant survives without wasting worker time
                        m.status = "SURVIVED"
                        survived.append(m)
                        continue

                    covering_tests = f_contexts.get(m.line_number, [])
                    if covering_tests:
                        # Dynamic test selection: execute only the tests covering this line
                        mutant_pytest_args = [_normalize_test_nodeid(t, snapshot_dir) for t in covering_tests[:15]]
                    else:
                        mutant_pytest_args = default_pytest_args
                else:
                    mutant_pytest_args = default_pytest_args

                switch_num = file_switch_map.get(f, {}).get(m.mutant_id)
                tasks.append((
                    temp_base_str,
                    snapshot_dir_str,
                    rel_f_str,
                    m.mutant_id,
                    m.line_number,
                    m.description,
                    m.original_line,
                    m.mutated_line,
                    m.mutated_source,
                    mutant_pytest_args,
                    baseline_errors,
                    effective_timeout,
                    env_pythonpath,
                    switch_num,
                ))

        active_mutant_count = len(tasks)
        total_tested_files_count = len(tested_files) - len(untested_files_set.intersection(set(tested_files)))

        # 7. Execute mutant tasks with ProcessPoolExecutor
        killed_count = 0
        runner_errors: List[Tuple[Mutant, str]] = []
        completed_mutants = 0
        file_completed_counts: Dict[str, int] = {}
        file_total_mutants: Dict[str, int] = {}
        for _, _, rel_f_str, m_id, *_ in tasks:
            file_total_mutants[rel_f_str] = file_total_mutants.get(rel_f_str, 0) + 1

        completed_files_set: Set[str] = set()
        last_progress_print = 0.0

        if not quiet and active_mutant_count > 0:
            print(f"DeployProof: Running {active_mutant_count} mutants across {actual_workers} workers in parallel...", flush=True)

        with ProcessPoolExecutor(max_workers=actual_workers) as executor:
            future_to_id = {
                executor.submit(_run_single_mutant_in_sandbox, *task): task[3]
                for task in tasks
            }

            for future in as_completed(future_to_id):
                m_id = future_to_id[future]
                mutant = mutants_by_id[m_id]
                completed_mutants += 1

                try:
                    res_dict = future.result()
                    m_status = res_dict["status"]
                    error_msg = res_dict["error_msg"]
                    mutant.status = m_status

                    if m_status == "KILLED":
                        killed_count += 1
                    elif m_status == "SURVIVED":
                        survived.append(mutant)
                    elif m_status == "RUNNER_ERROR":
                        runner_errors.append((mutant, error_msg or "Runner error"))
                    else:
                        survived.append(mutant)
                except Exception as e:
                    mutant.status = "RUNNER_ERROR"
                    runner_errors.append((mutant, f"Worker process failure: {type(e).__name__}: {e}"))

                # Track file completion
                try:
                    rel_key = mutant.file_path.relative_to(root).as_posix()
                except ValueError:
                    rel_key = mutant.file_path.name

                file_completed_counts[rel_key] = file_completed_counts.get(rel_key, 0) + 1
                if file_completed_counts[rel_key] == file_total_mutants.get(rel_key, 0):
                    completed_files_set.add(rel_key)

                # Live progress update
                now = time.time()
                if not quiet and (
                    (completed_mutants == 1)
                    or (completed_mutants % 5 == 0)
                    or (now - last_progress_print >= 5.0)
                    or (completed_mutants == active_mutant_count)
                ):
                    if (now - last_progress_print >= 0.5) or (completed_mutants == active_mutant_count):
                        last_progress_print = now
                        elapsed = now - start_time
                        elapsed_str = f"{int(elapsed // 60)}m{int(elapsed % 60):02d}s"
                        print(
                            f"  [{completed_mutants}/{active_mutant_count} mutants | {len(completed_files_set)}/{total_tested_files_count} files] elapsed: {elapsed_str}",
                            flush=True,
                        )

        if not quiet and active_mutant_count > 0:
            print("", flush=True)

        for f in untested_files_set:
            for m in file_mutants_map.get(f, []):
                survived.append(m)

        valid_mutants_count = killed_count + len(survived)
        if valid_mutants_count > 0:
            score = killed_count / valid_mutants_count * 100.0
        else:
            score = 0.0 if untested_files_set else 100.0

        return MutationResult(
            total_mutants=total_mutants_count,
            killed_mutants=killed_count,
            survived_mutants=survived,
            untested_files=sorted(untested_files_set),
            runner_errors=runner_errors,
            skipped_constructs=all_skipped,
            pruned_equivalent_mutants=all_pruned_equivalent,
            mutation_score=round(score, 1),
            duration_seconds=round(time.time() - start_time, 2),
            files_tested=target_files,
        )

    finally:
        _ACTIVE_TEMP_DIRS.discard(temp_base)
        try:
            temp_dir_obj.cleanup()
        except Exception:
            try:
                shutil.rmtree(temp_base, onerror=_on_rm_error)
            except Exception:
                pass


def run_mutation_tests(
    target_files: List[Path],
    repo_root: Optional[Path] = None,
    test_runner_timeout: float = 10.0,
    extra_pytest_args: Optional[List[str]] = None,
    workers: Optional[int] = None,
    is_full_repo: bool = False,
    base: Optional[str] = None,
    quiet: bool = False,
) -> MutationResult:
    """
    Top-level mutation testing router.
    
    If in --full-repo mode or multiple workers requested, delegates to isolated ProcessPoolExecutor.
    Otherwise, executes the fast sequential path for diff-scoped checks.
    """
    if is_full_repo or (workers is not None and workers > 1):
        return run_mutation_tests_parallel(
            target_files=target_files,
            repo_root=repo_root,
            test_runner_timeout=test_runner_timeout,
            extra_pytest_args=extra_pytest_args,
            workers=workers,
            is_full_repo=is_full_repo,
            base=base,
            quiet=quiet,
        )
    return _run_mutation_tests_sequential(
        target_files=target_files,
        repo_root=repo_root,
        test_runner_timeout=test_runner_timeout,
        extra_pytest_args=extra_pytest_args,
        is_full_repo=is_full_repo,
        base=base,
        quiet=quiet,
    )