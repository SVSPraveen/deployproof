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
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
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
    mutation_score: Optional[float] = 100.0
    duration_seconds: float = 0.0
    files_tested: List[Path] = field(default_factory=list)
    collection_error: Optional[str] = None
_CURRENT_MUTATED_FILE: Optional[Path] = None
_CURRENT_ORIGINAL_CONTENT: Optional[str] = None
_SIGNAL_HANDLER_INSTALLED: bool = False
_PREV_SIGINT: Any = None
_PREV_SIGTERM: Any = None
_PREV_SIGBREAK: Any = None

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
    """Signal handler for SIGINT, SIGTERM, and SIGBREAK to restore on-disk source before process exit."""
    _restore_current_mutant_file()
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
BINOP_MAP = {ast.Add: (ast.Sub, '+', '-'), ast.Sub: (ast.Add, '-', '+'), ast.Mult: (ast.Div, '*', '/'), ast.Div: (ast.Mult, '/', '*'), ast.FloorDiv: (ast.Div, '//', '/'), ast.Mod: (ast.Mult, '%', '*'), ast.Pow: (ast.Mult, '**', '*'), ast.BitAnd: (ast.BitOr, '&', '|'), ast.BitOr: (ast.BitAnd, '|', '&'), ast.BitXor: (ast.BitAnd, '^', '&')}
BOOLOP_MAP = {ast.And: (ast.Or, 'and', 'or'), ast.Or: (ast.And, 'or', 'and')}
AUGASSIGN_MAP = {ast.Add: (ast.Sub, '+=', '-='), ast.Sub: (ast.Add, '-=', '+='), ast.Mult: (ast.Div, '*=', '/='), ast.Div: (ast.Mult, '/=', '*=')}

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

    def visit_Await(self, node: ast.Await) -> None:
        self._record_skip(node, 'Await Expression', 'Async await call semantics and coroutine resolution not mutated by Tier 1')
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

class MutationCounter(ast.NodeVisitor):
    """Count number of mutable locations in an AST, excluding type annotations."""

    def __init__(self) -> None:
        self.count = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for d in node.decorator_list:
            self.visit(d)
        for default in node.args.defaults:
            if default:
                self.visit(default)
        for kw_default in node.args.kw_defaults:
            if kw_default:
                self.visit(kw_default)
        for stmt in node.body:
            self.visit(stmt)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        for d in node.decorator_list:
            self.visit(d)
        for default in node.args.defaults:
            if default:
                self.visit(default)
        for kw_default in node.args.kw_defaults:
            if kw_default:
                self.visit(kw_default)
        for stmt in node.body:
            self.visit(stmt)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.visit(node.target)
        if node.value:
            self.visit(node.value)

    def visit_arg(self, node: ast.arg) -> None:
        pass

    def visit_Call(self, node: ast.Call) -> None:
        if is_log_or_print_call(node):
            return
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
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

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, bool):
            self.count += 1
        elif isinstance(node.value, (int, float)) and (not isinstance(node.value, bool)):
            self.count += 1
        self.generic_visit(node)

class MutationTransformer(ast.NodeTransformer):
    """Applies a single mutation at the specified index, excluding type annotations."""

    def __init__(self, target_index: int) -> None:
        self.target_index = target_index
        self.current_index = 0
        self.applied_info: Optional[Tuple[int, str, str, str]] = None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node.decorator_list = [self.visit(d) for d in node.decorator_list]
        node.args.defaults = [self.visit(d) if d else None for d in node.args.defaults]
        node.args.kw_defaults = [self.visit(d) if d else None for d in node.args.kw_defaults]
        node.body = [self.visit(stmt) for stmt in node.body]
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        node.decorator_list = [self.visit(d) for d in node.decorator_list]
        node.args.defaults = [self.visit(d) if d else None for d in node.args.defaults]
        node.args.kw_defaults = [self.visit(d) if d else None for d in node.args.kw_defaults]
        node.body = [self.visit(stmt) for stmt in node.body]
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST:
        node.target = self.visit(node.target)
        if node.value:
            node.value = self.visit(node.value)
        return node

    def visit_arg(self, node: ast.arg) -> ast.AST:
        return node

    def visit_Call(self, node: ast.Call) -> ast.AST:
        if is_log_or_print_call(node):
            return node
        return self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> ast.AST:
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
        return node

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


def collect_skipped_constructs_for_file(file_path: Path) -> List[SkippedConstruct]:
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
    return collector.skipped

def generate_mutants_for_file(file_path: Path) -> List[Mutant]:
    """Generate all deterministic mutants for a single Python file."""
    try:
        source = file_path.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = source.splitlines()
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
        desc = transformer.applied_info[1] if transformer.applied_info else f'Mutation #{idx + 1}'
        old_val = transformer.applied_info[2] if transformer.applied_info and len(transformer.applied_info) > 2 else ''
        new_val = transformer.applied_info[3] if transformer.applied_info and len(transformer.applied_info) > 3 else ''
        col_offset = transformer.applied_info[4] if transformer.applied_info and len(transformer.applied_info) > 4 else None
        end_col_offset = transformer.applied_info[5] if transformer.applied_info and len(transformer.applied_info) > 5 else None
        raw_line = lines[lineno - 1] if 0 <= lineno - 1 < len(lines) else ''
        orig_line = raw_line.strip()
        if col_offset is not None and end_col_offset is not None and (0 <= col_offset <= end_col_offset <= len(raw_line)):
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
                    mut_lines = mutated_source.splitlines()
                    mut_line = mut_lines[lineno - 1].strip() if 0 <= lineno - 1 < len(mut_lines) else orig_line
        else:
            mut_lines = mutated_source.splitlines()
            mut_line = mut_lines[lineno - 1].strip() if 0 <= lineno - 1 < len(mut_lines) else orig_line
        mutant_id = f'{file_path.name}:{lineno}:mutant_{idx + 1}'
        mutants.append(Mutant(mutant_id=mutant_id, file_path=file_path, line_number=lineno, description=desc, original_line=orig_line, mutated_line=mut_line, mutated_source=mutated_source))
    return mutants

def discover_target_tests(target_files: List[Path], root: Path) -> List[str]:
    """Discover candidate pytest test targets relevant to the changed files."""
    matched_test_files: List[str] = []
    tests_dirs = [d for d in [root / 'tests', root / 'test'] if d.is_dir()]
    if not tests_dirs:
        tests_dirs = [root]
    for f in target_files:
        stem = f.stem
        stems = {stem}
        if stem.startswith('_'):
            stems.add(stem.lstrip('_'))
        if stem.endswith('s') and len(stem) > 1:
            stems.add(stem.rstrip('s'))
            if stem.startswith('_'):
                stems.add(stem.lstrip('_').rstrip('s'))
        else:
            stems.add(stem + 's')
            if stem.startswith('_'):
                stems.add(stem.lstrip('_') + 's')
        direct_matched: List[str] = []
        for t_dir in tests_dirs:
            for test_path in t_dir.rglob('*.py'):
                filename = test_path.name
                for s in stems:
                    if filename in (f'test_{s}.py', f'{s}_test.py', f'test_{s}s.py') or (s.endswith('s') and filename == f'test_{s[:-1]}.py'):
                        try:
                            rel = str(test_path.relative_to(root))
                        except ValueError:
                            rel = str(test_path)
                        if rel not in direct_matched:
                            direct_matched.append(rel)
            for s in stems:
                for match_dir in t_dir.rglob(s):
                    if match_dir.is_dir():
                        for test_file in match_dir.rglob('*.py'):
                            if test_file.name.startswith('test_') or test_file.name.endswith('_test.py'):
                                try:
                                    rel = str(test_file.relative_to(root))
                                except ValueError:
                                    rel = str(test_file)
                                if rel not in direct_matched:
                                    direct_matched.append(rel)
        if direct_matched:
            for m in direct_matched:
                if m not in matched_test_files:
                    matched_test_files.append(m)
        else:
            parent_name = f.parent.name
            parent_stems = {parent_name}
            if parent_name.startswith('_'):
                parent_stems.add(parent_name.lstrip('_'))
            for t_dir in tests_dirs:
                for test_path in t_dir.rglob('*.py'):
                    filename = test_path.name
                    for ps in parent_stems:
                        if filename in (f'test_{ps}.py', f'{ps}_test.py'):
                            try:
                                rel = str(test_path.relative_to(root))
                            except ValueError:
                                rel = str(test_path)
                            if rel not in matched_test_files:
                                matched_test_files.append(rel)
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
) -> Dict[str, Any]:
    """
    Execute a single mutant in a PID-isolated worker sandbox directory.
    
    Guarantees 100% process isolation without cross-worker file race conditions.
    Each worker process maintains its own private directory cloned from a clean snapshot.
    Restores sandbox file state after test execution.
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
        "--tb=no",
        "-o",
        f"cache_dir={worker_cache}",
        f"--basetemp={worker_tmp}",
    ]
    if baseline_errors == 0:
        cmd.append("-x")
    cmd.extend(pytest_args)

    status = "SURVIVED"
    error_msg = None

    try:
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


def _run_mutation_tests_sequential(
    target_files: List[Path],
    repo_root: Optional[Path] = None,
    test_runner_timeout: float = 10.0,
    extra_pytest_args: Optional[List[str]] = None,
) -> MutationResult:
    """
    Execute targeted sequential mutation testing across target files (diff-scoped mode).
    """
    root = (repo_root or Path.cwd()).resolve()
    start_time = time.time()
    file_mutants_map: Dict[Path, List[Mutant]] = {}
    all_skipped: List[SkippedConstruct] = []
    total_mutants_count = 0

    for f in target_files:
        if f.is_file() and f.suffix == '.py':
            f_mutants = generate_mutants_for_file(f)
            file_mutants_map[f] = f_mutants
            total_mutants_count += len(f_mutants)
            all_skipped.extend(collect_skipped_constructs_for_file(f))

    if total_mutants_count == 0:
        return MutationResult(total_mutants=0, killed_mutants=0, survived_mutants=[], untested_files=[], runner_errors=[], skipped_constructs=all_skipped, mutation_score=100.0, duration_seconds=round(time.time() - start_time, 2), files_tested=target_files)

    killed_count = 0
    survived: List[Mutant] = []
    runner_errors: List[Tuple[Mutant, str]] = []
    untested_files_set: Set[Path] = set()

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

            pytest_cmd = [sys.executable, '-B', '-m', 'pytest', '-q', '--tb=short', '-p', 'no:cacheprovider'] + pytest_args
            t0 = time.time()
            baseline_timeout = max(test_runner_timeout * 3.0, 45.0, len(pytest_args) * 15.0)

            try:
                baseline_res = subprocess.run(
                    pytest_cmd,
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    timeout=baseline_timeout,
                )
            except Exception as e:
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
                    collection_error=f'Execution exception during baseline test run: {type(e).__name__}: {e}',
                )

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

            effective_timeout = max(test_runner_timeout, baseline_duration * 3.0 + 5.0)
            baseline_has_errors = baseline_summary.get('errors', 0) > 0
            mutant_pytest_cmd = [sys.executable, '-B', '-m', 'pytest', '-q', '--tb=no', '-p', 'no:cacheprovider']
            if not baseline_has_errors:
                mutant_pytest_cmd.append('-x')
            mutant_pytest_cmd.extend(pytest_args)

            for mutant in mutants:
                original_code = mutant.file_path.read_text(encoding='utf-8', errors='replace')
                _CURRENT_MUTATED_FILE = mutant.file_path
                _CURRENT_ORIGINAL_CONTENT = original_code
                try:
                    mutant.file_path.write_text(mutant.mutated_source, encoding='utf-8')
                    res = subprocess.run(
                        mutant_pytest_cmd,
                        cwd=root,
                        env=env,
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
                    mutant.file_path.write_text(original_code, encoding='utf-8')
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
    quiet: bool = False,
) -> MutationResult:
    """
    Execute mutation testing across target files using an isolated multi-worker ProcessPoolExecutor.
    
    Each worker executes in its own isolated filesystem sandbox with live progress tracking.
    """
    root = (repo_root or Path.cwd()).resolve()
    start_time = time.time()

    # 1. Determine worker count (sane cap at 8 by default)
    max_workers = min(os.cpu_count() or 4, 8)
    if workers is not None and workers > 0:
        actual_workers = min(workers, 32)
    else:
        actual_workers = max_workers

    # 2. Collect mutants and skipped constructs
    file_mutants_map: Dict[Path, List[Mutant]] = {}
    all_skipped: List[SkippedConstruct] = []
    total_mutants_count = 0

    for f in target_files:
        if f.is_file() and f.suffix == '.py':
            f_mutants = generate_mutants_for_file(f)
            file_mutants_map[f] = f_mutants
            total_mutants_count += len(f_mutants)
            all_skipped.extend(collect_skipped_constructs_for_file(f))

    if total_mutants_count == 0:
        return MutationResult(
            total_mutants=0,
            killed_mutants=0,
            survived_mutants=[],
            untested_files=[],
            runner_errors=[],
            skipped_constructs=all_skipped,
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
            mutation_score=0.0,
            duration_seconds=round(time.time() - start_time, 2),
            files_tested=target_files,
        )

    # 4. Prepare worker sandboxes in temp directory
    temp_dir_obj = tempfile.TemporaryDirectory(prefix="deployproof_workers_")
    temp_base = Path(temp_dir_obj.name)

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

        # 5. Baseline runs for unique test suites
        suite_baseline_cache: Dict[Tuple[str, ...], Tuple[bool, int, float, bool, Optional[str]]] = {}
        file_baseline_info: Dict[Path, Tuple[int, float]] = {}
        env_snapshot = os.environ.copy()
        env_snapshot["PYTHONDONTWRITEBYTECODE"] = "1"
        paths_to_add = []
        if (snapshot_dir / "src").is_dir():
            paths_to_add.append(str(snapshot_dir / "src"))
        paths_to_add.append(str(snapshot_dir))
        if env_pythonpath:
            paths_to_add.append(env_pythonpath)
        env_snapshot["PYTHONPATH"] = os.pathsep.join(paths_to_add)

        snapshot_cache = snapshot_dir / ".pytest_cache"
        snapshot_tmp = snapshot_dir / ".pytest_tmp"

        for f in tested_files:
            pytest_args = file_test_map[f]
            suite_key = tuple(pytest_args)

            if suite_key not in suite_baseline_cache:
                t0 = time.time()
                baseline_timeout = max(test_runner_timeout * 3.0, 45.0, len(pytest_args) * 15.0)
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
                ] + pytest_args

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
                eff_timeout = max(test_runner_timeout, baseline_duration * 3.0 + 5.0)
                suite_baseline_cache[suite_key] = (no_tests, baseline_summary.get("errors", 0), eff_timeout, False, None)

            no_tests, base_errors, eff_timeout, _, _ = suite_baseline_cache[suite_key]
            if no_tests:
                untested_files_set.add(f)
                for m in file_mutants_map[f]:
                    m.status = 'SURVIVED'
            else:
                file_baseline_info[f] = (base_errors, eff_timeout)

        # 6. Build list of mutant tasks
        tasks = []
        mutants_by_id: Dict[str, Mutant] = {}
        temp_base_str = str(temp_base)
        snapshot_dir_str = str(snapshot_dir)

        for f, mutants in file_mutants_map.items():
            if f in untested_files_set or f not in file_baseline_info:
                continue
            baseline_errors, effective_timeout = file_baseline_info[f]
            pytest_args = file_test_map[f]
            try:
                rel_f_str = f.relative_to(root).as_posix()
            except ValueError:
                rel_f_str = f.name

            for m in mutants:
                mutants_by_id[m.mutant_id] = m
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
                    pytest_args,
                    baseline_errors,
                    effective_timeout,
                    env_pythonpath,
                ))

        active_mutant_count = len(tasks)
        total_tested_files_count = len(tested_files) - len(untested_files_set.intersection(set(tested_files)))

        # 7. Execute mutant tasks with ProcessPoolExecutor
        killed_count = 0
        survived: List[Mutant] = []
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
                if not quiet and (now - last_progress_print >= 2.0 or completed_mutants == active_mutant_count):
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
            mutation_score=round(score, 1),
            duration_seconds=round(time.time() - start_time, 2),
            files_tested=target_files,
        )

    finally:
        try:
            temp_dir_obj.cleanup()
        except Exception:
            pass


def run_mutation_tests(
    target_files: List[Path],
    repo_root: Optional[Path] = None,
    test_runner_timeout: float = 10.0,
    extra_pytest_args: Optional[List[str]] = None,
    workers: Optional[int] = None,
    is_full_repo: bool = False,
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
            quiet=quiet,
        )
    return _run_mutation_tests_sequential(
        target_files=target_files,
        repo_root=repo_root,
        test_runner_timeout=test_runner_timeout,
        extra_pytest_args=extra_pytest_args,
    )