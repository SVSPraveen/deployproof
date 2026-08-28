"""Deterministic AST mutation testing engine for DeployProof."""

import ast
import copy
import os
import re
import subprocess
import sys
import time
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
    status: str = "PENDING"  # PENDING, KILLED, SURVIVED, TIMEOUT, RUNNER_ERROR


@dataclass
class SkippedConstruct:
    """Represents an unsupported construct in source code that Tier 1 cannot mutate."""
    file_path: Path
    line_number: int
    construct_name: str
    description: str
    snippet: str = ""


@dataclass
class MutationResult:
    """Aggregated mutation testing results."""
    total_mutants: int
    killed_mutants: int
    survived_mutants: List[Mutant] = field(default_factory=list)
    untested_files: List[Path] = field(default_factory=list)
    runner_errors: List[Tuple[Mutant, str]] = field(default_factory=list)
    skipped_constructs: List[SkippedConstruct] = field(default_factory=list)
    mutation_score: float = 100.0
    duration_seconds: float = 0.0
    files_tested: List[Path] = field(default_factory=list)


# Mutation mappings
COMPARE_MAP = {
    ast.Eq: (ast.NotEq, "==", "!="),
    ast.NotEq: (ast.Eq, "!=", "=="),
    ast.Lt: (ast.GtE, "<", ">="),
    ast.LtE: (ast.Gt, "<=", ">"),
    ast.Gt: (ast.LtE, ">", "<="),
    ast.GtE: (ast.Lt, ">=", "<"),
    ast.In: (ast.NotIn, "in", "not in"),
    ast.NotIn: (ast.In, "not in", "in"),
    ast.Is: (ast.IsNot, "is", "is not"),
    ast.IsNot: (ast.Is, "is not", "is"),
}

BINOP_MAP = {
    ast.Add: (ast.Sub, "+", "-"),
    ast.Sub: (ast.Add, "-", "+"),
    ast.Mult: (ast.Div, "*", "/"),
    ast.Div: (ast.Mult, "/", "*"),
    ast.FloorDiv: (ast.Div, "//", "/"),
    ast.Mod: (ast.Mult, "%", "*"),
    ast.Pow: (ast.Mult, "**", "*"),
    ast.BitAnd: (ast.BitOr, "&", "|"),
    ast.BitOr: (ast.BitAnd, "|", "&"),
    ast.BitXor: (ast.BitAnd, "^", "&"),
}

BOOLOP_MAP = {
    ast.And: (ast.Or, "and", "or"),
    ast.Or: (ast.And, "or", "and"),
}

AUGASSIGN_MAP = {
    ast.Add: (ast.Sub, "+=", "-="),
    ast.Sub: (ast.Add, "-=", "+="),
    ast.Mult: (ast.Div, "*=", "/="),
    ast.Div: (ast.Mult, "/=", "*="),
}


class SkippedConstructCollector(ast.NodeVisitor):
    """Identifies and records unsupported Python constructs during AST traversal."""
    def __init__(self, file_path: Path, source_lines: List[str]) -> None:
        self.file_path = file_path
        self.source_lines = source_lines
        self.skipped: List[SkippedConstruct] = []
        self._seen: Set[Tuple[int, str]] = set()

    def _record_skip(self, node: ast.AST, construct_name: str, description: str) -> None:
        lineno = getattr(node, "lineno", 1)
        key = (lineno, construct_name)
        if key not in self._seen:
            self._seen.add(key)
            snippet = (
                self.source_lines[lineno - 1].strip()
                if 0 <= lineno - 1 < len(self.source_lines)
                else ""
            )
            self.skipped.append(
                SkippedConstruct(
                    file_path=self.file_path,
                    line_number=lineno,
                    construct_name=construct_name,
                    description=description,
                    snippet=snippet,
                )
            )

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._record_skip(
            node,
            "Walrus Operator (:=)",
            "Walrus assignment expression target binding not mutated by Tier 1",
        )
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        self._record_skip(
            node,
            "Match Statement Pattern",
            "Structural pattern matching shapes/rules not mutated by Tier 1",
        )
        self.generic_visit(node)

    def visit_Await(self, node: ast.Await) -> None:
        self._record_skip(
            node,
            "Await Expression",
            "Async await call semantics and coroutine resolution not mutated by Tier 1",
        )
        self.generic_visit(node)

    def visit_Yield(self, node: ast.Yield) -> None:
        self._record_skip(
            node,
            "Yield Statement",
            "Generator yield statement semantics not mutated by Tier 1",
        )
        self.generic_visit(node)

    def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
        self._record_skip(
            node,
            "Yield From Statement",
            "Generator yield from statement semantics not mutated by Tier 1",
        )
        self.generic_visit(node)


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
        # Note: node.returns and arg.annotation are deliberately NOT visited
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
        elif isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            self.count += 1
        self.generic_visit(node)


class MutationTransformer(ast.NodeTransformer):
    """Applies a single mutation at the specified index, excluding type annotations."""
    def __init__(self, target_index: int) -> None:
        self.target_index = target_index
        self.current_index = 0
        self.applied_info: Optional[Tuple[int, str, str]] = None  # (line, desc, mutated_line_code)

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

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        new_ops = list(node.ops)
        for i, op in enumerate(node.ops):
            op_type = type(op)
            if op_type in COMPARE_MAP:
                if self.current_index == self.target_index:
                    new_cls, old_s, new_s = COMPARE_MAP[op_type]
                    new_ops[i] = new_cls()
                    self.applied_info = (
                        getattr(node, "lineno", 1),
                        f"Replace comparison '{old_s}' with '{new_s}'",
                        "",
                    )
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
                self.applied_info = (
                    getattr(node, "lineno", 1),
                    f"Replace binary operator '{old_s}' with '{new_s}'",
                    "",
                )
            self.current_index += 1
        return node

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        self.generic_visit(node)
        op_type = type(node.op)
        if op_type in BOOLOP_MAP:
            if self.current_index == self.target_index:
                new_cls, old_s, new_s = BOOLOP_MAP[op_type]
                node.op = new_cls()
                self.applied_info = (
                    getattr(node, "lineno", 1),
                    f"Replace logical operator '{old_s}' with '{new_s}'",
                    "",
                )
            self.current_index += 1
        return node

    def visit_AugAssign(self, node: ast.AugAssign) -> ast.AST:
        self.generic_visit(node)
        op_type = type(node.op)
        if op_type in AUGASSIGN_MAP:
            if self.current_index == self.target_index:
                new_cls, old_s, new_s = AUGASSIGN_MAP[op_type]
                node.op = new_cls()
                self.applied_info = (
                    getattr(node, "lineno", 1),
                    f"Replace augmented assignment '{old_s}' with '{new_s}'",
                    "",
                )
            self.current_index += 1
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.value, bool):
            if self.current_index == self.target_index:
                old_val = node.value
                node.value = not node.value
                self.applied_info = (
                    getattr(node, "lineno", 1),
                    f"Replace boolean literal '{old_val}' with '{node.value}'",
                    "",
                )
            self.current_index += 1
        elif isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            if self.current_index == self.target_index:
                old_num = node.value
                new_num = old_num + 1 if old_num != 0 else 1
                node.value = new_num
                self.applied_info = (
                    getattr(node, "lineno", 1),
                    f"Replace numeric constant '{old_num}' with '{new_num}'",
                    "",
                )
            self.current_index += 1
        return node


def parse_pytest_summary(output: str) -> Dict[str, Any]:
    """
    Parse pytest stdout/stderr to inspect whether any tests actually executed.
    
    Returns a dict with test counts and boolean no_tests_ran.
    """
    lowered = output.lower()
    if "no tests ran" in lowered or "no test was collected" in lowered or "0 selected" in lowered:
        return {"passed": 0, "failed": 0, "errors": 0, "total": 0, "no_tests_ran": True}

    passed_m = re.search(r"(\d+)\s+passed", output)
    failed_m = re.search(r"(\d+)\s+failed", output)
    errors_m = re.search(r"(\d+)\s+error", output)

    passed = int(passed_m.group(1)) if passed_m else 0
    failed = int(failed_m.group(1)) if failed_m else 0
    errors = int(errors_m.group(1)) if errors_m else 0
    total = passed + failed

    no_tests = (total == 0 and errors == 0)
    return {
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "total": total,
        "no_tests_ran": no_tests,
    }


def collect_skipped_constructs_for_file(file_path: Path) -> List[SkippedConstruct]:
    """Identify unsupported constructs in a file that Tier 1 skips."""
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
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
        source = file_path.read_text(encoding="utf-8", errors="replace")
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
        desc = transformer.applied_info[1] if transformer.applied_info else f"Mutation #{idx+1}"

        orig_line = lines[lineno - 1].strip() if 0 <= lineno - 1 < len(lines) else ""
        mut_lines = mutated_source.splitlines()
        mut_line = mut_lines[lineno - 1].strip() if 0 <= lineno - 1 < len(mut_lines) else ""

        mutant_id = f"{file_path.name}:{lineno}:mutant_{idx+1}"

        mutants.append(
            Mutant(
                mutant_id=mutant_id,
                file_path=file_path,
                line_number=lineno,
                description=desc,
                original_line=orig_line,
                mutated_line=mut_line,
                mutated_source=mutated_source,
            )
        )

    return mutants


def run_mutation_tests(
    target_files: List[Path],
    repo_root: Optional[Path] = None,
    test_runner_timeout: float = 10.0,
    extra_pytest_args: Optional[List[str]] = None,
) -> MutationResult:
    """
    Execute mutation testing across the specified target files.
    """
    root = (repo_root or Path.cwd()).resolve()
    start_time = time.time()

    all_mutants: List[Mutant] = []
    all_skipped: List[SkippedConstruct] = []

    for f in target_files:
        if f.is_file() and f.suffix == ".py":
            all_mutants.extend(generate_mutants_for_file(f))
            all_skipped.extend(collect_skipped_constructs_for_file(f))

    if not all_mutants:
        return MutationResult(
            total_mutants=0,
            killed_mutants=0,
            survived_mutants=[],
            untested_files=[],
            runner_errors=[],
            skipped_constructs=all_skipped,
            mutation_score=100.0,
            duration_seconds=time.time() - start_time,
            files_tested=target_files,
        )

    killed_count = 0
    survived: List[Mutant] = []
    runner_errors: List[Tuple[Mutant, str]] = []
    untested_files_set: Set[Path] = set()

    # Prepare environment with injected PYTHONPATH
    env = os.environ.copy()
    current_pythonpath = env.get("PYTHONPATH", "")
    paths_to_add = [str(root)]
    if (root / "src").is_dir():
        paths_to_add.append(str(root / "src"))
    new_pythonpath = os.pathsep.join(paths_to_add)
    if current_pythonpath:
        new_pythonpath = f"{new_pythonpath}{os.pathsep}{current_pythonpath}"
    env["PYTHONPATH"] = new_pythonpath

    pytest_cmd = [sys.executable, "-m", "pytest", "-q", "--tb=no"]
    if extra_pytest_args:
        pytest_cmd.extend(extra_pytest_args)

    # 1. Baseline pre-flight check
    baseline_has_no_tests = False
    baseline_duration = 1.0
    try:
        t0 = time.time()
        baseline_res = subprocess.run(
            pytest_cmd,
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(test_runner_timeout * 2, 20.0),
        )
        baseline_duration = max(time.time() - t0, 0.5)
        combined_output = baseline_res.stdout + "\n" + baseline_res.stderr
        summary = parse_pytest_summary(combined_output)

        if baseline_res.returncode == 5 or summary["no_tests_ran"]:
            # Baseline collected 0 tests
            baseline_has_no_tests = True
            untested_files_set.update(target_files)
        elif baseline_res.returncode in (2, 3, 4) or summary["errors"] > 0:
            err_output = combined_output.strip()
            if "ModuleNotFoundError" in err_output or "ImportError" in err_output:
                print(
                    "\n[!] Test suite failed to run before mutations (ModuleNotFoundError / ImportError).\n"
                    "    If this is a newly cloned repo, run 'pip install -e .' first to install dependencies and entry points.\n",
                    file=sys.stderr,
                )
    except Exception:
        pass

    # Dynamic timeout scaled to environment baseline speed
    effective_timeout = max(test_runner_timeout, baseline_duration * 3.0 + 5.0)

    # If baseline has NO tests at all, all mutants automatically survive without slow subprocesses
    if baseline_has_no_tests:
        for mutant in all_mutants:
            mutant.status = "SURVIVED"
            survived.append(mutant)

        return MutationResult(
            total_mutants=len(all_mutants),
            killed_mutants=0,
            survived_mutants=survived,
            untested_files=sorted(untested_files_set),
            runner_errors=[],
            skipped_constructs=all_skipped,
            mutation_score=0.0,
            duration_seconds=round(time.time() - start_time, 2),
            files_tested=target_files,
        )

    # 2. Execute test runner for each mutant
    for mutant in all_mutants:
        original_code = mutant.file_path.read_text(encoding="utf-8", errors="replace")
        try:
            # Inject mutant
            mutant.file_path.write_text(mutant.mutated_source, encoding="utf-8")

            # Run test suite with injected environment
            res = subprocess.run(
                pytest_cmd,
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=effective_timeout,
            )

            combined_out = res.stdout + "\n" + res.stderr
            summary = parse_pytest_summary(combined_out)

            # Precise pytest output and exit code classification:
            if res.returncode == 5 or summary["no_tests_ran"]:
                # Zero tests ran -> mutant survived untested
                mutant.status = "SURVIVED"
                survived.append(mutant)
                untested_files_set.add(mutant.file_path)
            elif summary["failed"] > 0 or res.returncode == 1:
                # Tests executed and failed -> mutant caught
                mutant.status = "KILLED"
                killed_count += 1
            elif res.returncode == 0 and summary["passed"] > 0:
                # Tests executed and passed -> mutant survived undetected
                mutant.status = "SURVIVED"
                survived.append(mutant)
            elif res.returncode in (2, 3, 4) or summary["errors"] > 0:
                # Syntax / usage / runner collection error
                mutant.status = "RUNNER_ERROR"
                err_msg = f"Pytest exit code {res.returncode}: {res.stderr.strip() or res.stdout.strip()}"
                runner_errors.append((mutant, err_msg))
            else:
                # Default fallback
                mutant.status = "SURVIVED"
                survived.append(mutant)

        except subprocess.TimeoutExpired:
            # Timeout on a mutant when baseline had working tests -> KILLED (infinite loop)
            mutant.status = "KILLED"
            killed_count += 1
        except Exception as e:
            mutant.status = "RUNNER_ERROR"
            runner_errors.append((mutant, f"Execution exception: {type(e).__name__}: {e}"))
        finally:
            # Strict guarantee: restore original source code
            mutant.file_path.write_text(original_code, encoding="utf-8")

    # Score calculation: valid evaluated mutants (excluding runner errors)
    valid_mutants_count = killed_count + len(survived)
    if valid_mutants_count > 0:
        score = (killed_count / valid_mutants_count * 100.0)
    else:
        score = 0.0 if untested_files_set else 100.0

    return MutationResult(
        total_mutants=len(all_mutants),
        killed_mutants=killed_count,
        survived_mutants=survived,
        untested_files=sorted(untested_files_set),
        runner_errors=runner_errors,
        skipped_constructs=all_skipped,
        mutation_score=round(score, 1),
        duration_seconds=round(time.time() - start_time, 2),
        files_tested=target_files,
    )
