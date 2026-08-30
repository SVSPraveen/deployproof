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
from concurrent.futures import ThreadPoolExecutor, as_completed
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

def run_mutation_tests(target_files: List[Path], repo_root: Optional[Path]=None, test_runner_timeout: float=10.0, extra_pytest_args: Optional[List[str]]=None) -> MutationResult:
    """
    Execute mutation testing across the specified target files.
    """
    root = (repo_root or Path.cwd()).resolve()
    start_time = time.time()
    all_mutants: List[Mutant] = []
    all_skipped: List[SkippedConstruct] = []
    for f in target_files:
        if f.is_file() and f.suffix == '.py':
            all_mutants.extend(generate_mutants_for_file(f))
            all_skipped.extend(collect_skipped_constructs_for_file(f))
    if not all_mutants:
        return MutationResult(total_mutants=0, killed_mutants=0, survived_mutants=[], untested_files=[], runner_errors=[], skipped_constructs=all_skipped, mutation_score=100.0, duration_seconds=round(time.time() - start_time, 2), files_tested=target_files)
    killed_count = 0
    survived: List[Mutant] = []
    runner_errors: List[Tuple[Mutant, str]] = []
    untested_files_set: Set[Path] = set()
    env = os.environ.copy()
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    current_pythonpath = env.get('PYTHONPATH', '')
    paths_to_add = [str(root)]
    if (root / 'src').is_dir():
        paths_to_add.append(str(root / 'src'))
    new_pythonpath = os.pathsep.join(paths_to_add)
    if current_pythonpath:
        new_pythonpath = f'{new_pythonpath}{os.pathsep}{current_pythonpath}'
    env['PYTHONPATH'] = new_pythonpath
    if extra_pytest_args:
        pytest_args = list(extra_pytest_args)
    else:
        targeted_tests = discover_target_tests(target_files, root)
        pytest_args = targeted_tests if targeted_tests else []
    pytest_cmd = [sys.executable, '-B', '-m', 'pytest', '-q', '--tb=short', '-p', 'no:cacheprovider'] + pytest_args
    baseline_has_no_tests = False
    baseline_duration = 1.0
    baseline_summary: Dict[str, Any] = {}
    try:
        t0 = time.time()
        baseline_timeout = max(test_runner_timeout * 3.0, 45.0, len(pytest_args) * 15.0 if pytest_args else 30.0)
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
                total_mutants=len(all_mutants),
                killed_mutants=0,
                survived_mutants=[],
                untested_files=[],
                runner_errors=[],
                skipped_constructs=all_skipped,
                mutation_score=None,
                duration_seconds=round(time.time() - start_time, 2),
                files_tested=target_files,
                collection_error=err_msg,
            )
        if baseline_res.returncode == 5 or baseline_summary["no_tests_ran"]:
            if pytest_args:
                fallback_timeout = max(test_runner_timeout * 3.0, 45.0)
                fallback_res = subprocess.run(
                    [sys.executable, "-B", "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider"],
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=fallback_timeout,
                )
                fb_combined = fallback_res.stdout + '\n' + fallback_res.stderr
                fb_summary = parse_pytest_summary(fb_combined)
                is_fb_collection_error = fallback_res.returncode in (2, 3, 4) or 'modulenotfounderror' in fb_combined.lower() or 'importerror' in fb_combined.lower() or ('error during collection' in fb_combined.lower()) or ('error while loading conftest' in fb_combined.lower()) or ('zoneinfonotfounderror' in fb_combined.lower()) or (fb_summary.get('errors', 0) > 0 and fb_summary.get('passed', 0) == 0 and (fb_summary.get('failed', 0) == 0))
                if is_fb_collection_error:
                    err_msg = extract_collection_error(fb_combined, fallback_res.returncode)
                    return MutationResult(total_mutants=len(all_mutants), killed_mutants=0, survived_mutants=[], untested_files=[], runner_errors=[], skipped_constructs=all_skipped, mutation_score=None, duration_seconds=round(time.time() - start_time, 2), files_tested=target_files, collection_error=err_msg)
                if fallback_res.returncode == 5 or fb_summary['no_tests_ran']:
                    baseline_has_no_tests = True
                    untested_files_set.update(target_files)
                else:
                    pytest_args = []
                    baseline_summary = fb_summary
            else:
                baseline_has_no_tests = True
                untested_files_set.update(target_files)
    except Exception as e:
        return MutationResult(total_mutants=len(all_mutants), killed_mutants=0, survived_mutants=[], untested_files=[], runner_errors=[], skipped_constructs=all_skipped, mutation_score=None, duration_seconds=round(time.time() - start_time, 2), files_tested=target_files, collection_error=f'Execution exception during baseline test run: {type(e).__name__}: {e}')
    effective_timeout = max(test_runner_timeout, baseline_duration * 3.0 + 5.0)
    if baseline_has_no_tests:
        for mutant in all_mutants:
            mutant.status = 'SURVIVED'
            survived.append(mutant)
        return MutationResult(total_mutants=len(all_mutants), killed_mutants=0, survived_mutants=survived, untested_files=sorted(untested_files_set), runner_errors=[], skipped_constructs=all_skipped, mutation_score=0.0, duration_seconds=round(time.time() - start_time, 2), files_tested=target_files)
    baseline_has_errors = baseline_summary.get('errors', 0) > 0
    mutant_pytest_cmd = [sys.executable, '-B', '-m', 'pytest', '-q', '--tb=no', '-p', 'no:cacheprovider']
    if not baseline_has_errors:
        mutant_pytest_cmd.append('-x')
    mutant_pytest_cmd.extend(pytest_args)
    global _CURRENT_MUTATED_FILE, _CURRENT_ORIGINAL_CONTENT
    install_mutation_signal_handlers()
    try:
        for mutant in all_mutants:
            original_code = mutant.file_path.read_text(encoding='utf-8', errors='replace')
            _CURRENT_MUTATED_FILE = mutant.file_path
            _CURRENT_ORIGINAL_CONTENT = original_code
            try:
                mutant.file_path.write_text(mutant.mutated_source, encoding='utf-8')
                res = subprocess.run(mutant_pytest_cmd, cwd=root, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=effective_timeout)
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
                elif mut_passed > 0 and mut_failed == 0:
                    mutant.status = 'SURVIVED'
                    survived.append(mutant)
                elif mut_errors > baseline_errors or res.returncode in (2, 3, 4):
                    mutant.status = 'RUNNER_ERROR'
                    err_msg = f'Pytest exit code {res.returncode}: {res.stderr.strip() or res.stdout.strip()}'
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
    return MutationResult(total_mutants=len(all_mutants), killed_mutants=killed_count, survived_mutants=survived, untested_files=sorted(untested_files_set), runner_errors=runner_errors, skipped_constructs=all_skipped, mutation_score=round(score, 1), duration_seconds=round(time.time() - start_time, 2), files_tested=target_files)