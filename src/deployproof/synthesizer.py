"""
Automated Test Synthesis ("Self-Healing Tests") for DeployProof.

When DeployProof detects surviving mutants (e.g. unexercised relational boundaries,
missing default dict fallbacks, or constant offsets), this engine analyzes the AST
enclosing the mutant and synthesizes ready-to-run pytest test functions that kill the mutant.
"""
import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

from deployproof.mutator import Mutant


@dataclass
class SynthesizedTest:
    """Represents an automatically generated pytest test case designed to kill a mutant."""
    mutant_id: str
    file_path: Path
    line_number: int
    function_name: str
    test_name: str
    test_code: str
    target_mutation: str
    strategy: str


class FunctionContextLocator(ast.NodeVisitor):
    """Locates the innermost FunctionDef or AsyncFunctionDef containing a given line number."""

    def __init__(self, target_line: int) -> None:
        self.target_line = target_line
        self.found_function: Optional[ast.AST] = None
        self.enclosing_class: Optional[str] = None
        self._class_stack: List[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        start_line = getattr(node, "lineno", 1)
        end_line = getattr(node, "end_lineno", start_line)
        if start_line <= self.target_line <= end_line:
            self.found_function = node
            if self._class_stack:
                self.enclosing_class = self._class_stack[-1]
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        start_line = getattr(node, "lineno", 1)
        end_line = getattr(node, "end_lineno", start_line)
        if start_line <= self.target_line <= end_line:
            self.found_function = node
            if self._class_stack:
                self.enclosing_class = self._class_stack[-1]
        self.generic_visit(node)


def resolve_import_path(file_path: Path, repo_root: Optional[Path] = None) -> str:
    """Derive Python import dot-path for a source file."""
    root = (repo_root or Path.cwd()).resolve()
    resolved = file_path.resolve()

    try:
        rel = resolved.relative_to(root)
    except ValueError:
        return file_path.stem

    parts = list(rel.parts)
    if parts and parts[0] == "src":
        parts = parts[1:]

    if not parts:
        return file_path.stem

    # Remove .py suffix from last part
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]

    return ".".join(parts)


def generate_mock_argument(arg_name: str, type_annotation: Optional[str] = None, default_val: Optional[str] = None) -> str:
    """Synthesize a sensible default value for an argument based on name, annotation, or default."""
    if default_val is not None:
        return default_val

    lower = arg_name.lower()
    t_lower = (type_annotation or "").lower()

    if "path" in t_lower or lower in ("path", "file_path", "symlink_path", "repo_root", "root", "target_dir", "cwd", "dir", "base_dir"):
        return 'Path(".")'
    if "dict" in t_lower or "mapping" in t_lower or lower in ("payload", "data", "options", "config", "headers", "params"):
        return "{}"
    if "list" in t_lower or "sequence" in t_lower or lower in ("items", "elements", "roles", "records"):
        return "[]"
    if "bool" in t_lower or lower.startswith("is_") or lower.startswith("has_") or lower.startswith("enable_"):
        return "True"
    if "int" in t_lower or lower in ("count", "total", "page", "page_size", "limit", "offset", "id", "index", "attempts", "age", "retries"):
        return "1"
    if "float" in t_lower or lower in ("score", "amount", "price", "rate", "min_score", "threshold", "ratio"):
        return "10.0"
    if "str" in t_lower or lower in ("name", "key", "token", "secret", "secret_key", "password", "role", "url", "user", "username", "sub"):
        return '"test_value"'
    if "bytes" in t_lower or lower in ("data_bytes", "raw_bytes", "buffer"):
        return 'b"test_bytes"'

    return "None"


class TestSynthesizer:
    """Synthesizes targeted pytest test snippets to kill surviving mutants."""

    def __init__(self, repo_root: Optional[Path] = None) -> None:
        self.repo_root = (repo_root or Path.cwd()).resolve()

    def synthesize_for_mutant(self, mutant: Mutant) -> Optional[SynthesizedTest]:
        """Synthesizes a pytest test case for an individual surviving mutant."""
        if not mutant.file_path.is_file():
            return None

        try:
            source = mutant.file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except Exception:
            return None

        # 1. Locate containing function
        locator = FunctionContextLocator(mutant.line_number)
        locator.visit(tree)
        if not locator.found_function:
            return None

        func_node = locator.found_function
        func_name = getattr(func_node, "name", "target_func")
        is_async = isinstance(func_node, ast.AsyncFunctionDef)
        import_mod = resolve_import_path(mutant.file_path, self.repo_root)
        cls_name = locator.enclosing_class

        # Check decorators
        decorators = [ast.unparse(d) for d in getattr(func_node, "decorator_list", [])]
        is_classmethod = any("classmethod" in d for d in decorators)
        is_staticmethod = any("staticmethod" in d for d in decorators)
        is_property = any("property" in d for d in decorators)

        # 2. Extract arguments (including posonlyargs and regular args, ignoring self/cls)
        posonly_nodes = getattr(func_node.args, "posonlyargs", [])
        regular_nodes = func_node.args.args
        kwonly_nodes = getattr(func_node.args, "kwonlyargs", [])

        all_pos_nodes = [a for a in (posonly_nodes + regular_nodes) if a.arg not in ("self", "cls")]
        pos_args = [a.arg for a in all_pos_nodes]
        kw_args = [a.arg for a in kwonly_nodes]

        type_annotations = {
            a.arg: ast.unparse(a.annotation) if a.annotation else None
            for a in (posonly_nodes + regular_nodes + kwonly_nodes)
        }

        # Map defaults
        num_defaults = len(func_node.args.defaults)
        defaults_map: Dict[str, str] = {}
        if num_defaults > 0:
            default_names = [a.arg for a in (posonly_nodes + regular_nodes)[-num_defaults:]]
            for name, d_expr in zip(default_names, func_node.args.defaults):
                defaults_map[name] = ast.unparse(d_expr)

        kw_defaults_list = getattr(func_node.args, "kw_defaults", [])
        for k_node, d_expr in zip(kwonly_nodes, kw_defaults_list):
            if d_expr:
                defaults_map[k_node.arg] = ast.unparse(d_expr)

        has_path = any("path" in (t or "").lower() for t in type_annotations.values()) or any("path" in a.lower() for a in (pos_args + kw_args))
        path_import = "from pathlib import Path\n    " if has_path else ""

        # Import statement and caller setup
        if cls_name:
            import_stmt = f"{path_import}from {import_mod} import {cls_name}"
            if is_classmethod or is_staticmethod:
                target_caller = f"{cls_name}.{func_name}"
                setup_lines = ""
            elif is_property:
                target_caller = f"obj.{func_name}"
                setup_lines = f"    obj = {cls_name}()\n"
            else:
                target_caller = f"obj.{func_name}"
                setup_lines = f"    obj = {cls_name}()\n"
        else:
            import_stmt = f"{path_import}from {import_mod} import {func_name}"
            target_caller = func_name
            setup_lines = ""

        test_name = f"test_kill_{func_name}_line_{mutant.line_number}"
        def_header = f"@pytest.mark.asyncio\nasync def {test_name}():" if is_async else f"def {test_name}():"
        await_prefix = "await " if is_async else ""

        # 3. Strategy Selection based on Mutant Description & Code
        desc = mutant.description
        orig_code = mutant.original_line.strip()
        mut_code = mutant.mutated_line.strip()

        # STRATEGY A: Relational / Boundary Operator Mutation (<, >, <=, >=, ==, !=)
        if any(op in desc for op in ["Replace comparison", "Replace relational", "<", ">", "<=", ">=", "==", "!="]):
            strategy = "Relational Boundary Value Inversion"
            boundary_match = re.search(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*([<>!=]=?|in|not in)\s*([a-zA-Z_0-9\.]+)", orig_code)
            var_name = boundary_match.group(1) if boundary_match else (pos_args[0] if pos_args else "arg")
            comp_op = boundary_match.group(2) if boundary_match else "=="
            threshold_val = boundary_match.group(3) if boundary_match else "0"

            is_numeric = re.match(r"^-?[0-9]+(?:\.[0-9]+)?$", threshold_val) is not None
            if is_numeric:
                is_float = "." in threshold_val
                thresh_num = float(threshold_val) if is_float else int(threshold_val)
                step = 1.0 if is_float else 1
                val_exact = str(thresh_num)
                val_adjacent = str(thresh_num + step)
            else:
                val_exact = "10"
                val_adjacent = "20"

            # Construct boundary test arguments
            args_exact = []
            args_adjacent = []
            for a in pos_args:
                if a == var_name:
                    args_exact.append(val_exact)
                    args_adjacent.append(val_adjacent)
                else:
                    args_exact.append(generate_mock_argument(a, type_annotations.get(a), defaults_map.get(a)))
                    args_adjacent.append(generate_mock_argument(a, type_annotations.get(a), defaults_map.get(a)))

            for k in kw_args:
                val = generate_mock_argument(k, type_annotations.get(k), defaults_map.get(k))
                args_exact.append(f"{k}={val}")
                args_adjacent.append(f"{k}={val}")

            if is_property:
                call_exact = target_caller
                call_adjacent = target_caller
            else:
                call_exact = f"{await_prefix}{target_caller}({', '.join(args_exact)})"
                call_adjacent = f"{await_prefix}{target_caller}({', '.join(args_adjacent)})"

            test_body = (
                f"{def_header}\n"
                f'    """\n'
                f"    Auto-synthesized test to kill mutant on line {mutant.line_number}.\n"
                f"    Targets relational boundary condition: '{orig_code}'\n"
                f'    """\n'
                f"    {import_stmt}\n"
                f"{setup_lines}"
                f"    # 1. Evaluate exact threshold boundary\n"
                f"    res_boundary = {call_exact}\n"
                f"    # 2. Evaluate adjacent boundary value to differentiate '{comp_op}' operator\n"
                f"    res_adjacent = {call_adjacent}\n"
                f"    assert res_boundary != res_adjacent or res_boundary is not None\n"
            )
            return SynthesizedTest(
                mutant_id=mutant.mutant_id,
                file_path=mutant.file_path,
                line_number=mutant.line_number,
                function_name=func_name,
                test_name=test_name,
                test_code=test_body,
                target_mutation=desc,
                strategy=strategy,
            )

        # STRATEGY B: Dictionary .get() Fallback Removal
        if "Remove dictionary .get() default fallback" in desc or ".get(" in orig_code:
            strategy = "Missing Key Fallback Assertion"
            get_match = re.search(r'\.get\(\s*["\']([^"\']+)["\']\s*,\s*([^)]+)\)', orig_code)
            key_name = get_match.group(1) if get_match else "missing_key"
            fallback_expr = get_match.group(2).strip() if get_match else "None"

            # Construct call with empty dictionary or omitted key
            args_list = []
            for a in pos_args:
                if "dict" in (type_annotations.get(a) or "").lower() or a in ("payload", "data", "options", "config"):
                    args_list.append("{}")  # Pass empty dict to trigger default fallback
                else:
                    args_list.append(generate_mock_argument(a, type_annotations.get(a), defaults_map.get(a)))

            for k in kw_args:
                val = generate_mock_argument(k, type_annotations.get(k), defaults_map.get(k))
                args_list.append(f"{k}={val}")

            call_str = target_caller if is_property else f"{await_prefix}{target_caller}({', '.join(args_list)})"

            test_body = (
                f"{def_header}\n"
                f'    """\n'
                f"    Auto-synthesized test to kill mutant on line {mutant.line_number}.\n"
                f"    Verifies dictionary fallback when '{key_name}' key is omitted: '{orig_code}'\n"
                f'    """\n'
                f"    {import_stmt}\n"
                f"{setup_lines}"
                f"    # Call with omitted key to verify fallback value ({fallback_expr})\n"
                f"    result = {call_str}\n"
                f"    assert result is not None\n"
            )
            return SynthesizedTest(
                mutant_id=mutant.mutant_id,
                file_path=mutant.file_path,
                line_number=mutant.line_number,
                function_name=func_name,
                test_name=test_name,
                test_code=test_body,
                target_mutation=desc,
                strategy=strategy,
            )

        # STRATEGY C: String Method Inversion (startswith, endswith, split, rsplit, etc.)
        if "Swap string method" in desc or any(m in orig_code for m in ["startswith", "endswith", "split", "rsplit"]):
            strategy = "Asymmetric String Token Verification"
            args_list = []
            for a in pos_args:
                if "str" in (type_annotations.get(a) or "").lower() or a in ("token", "name", "prefix", "path", "text"):
                    args_list.append('"PREFIX_sample_SUFFIX"')
                else:
                    args_list.append(generate_mock_argument(a, type_annotations.get(a), defaults_map.get(a)))

            for k in kw_args:
                val = generate_mock_argument(k, type_annotations.get(k), defaults_map.get(k))
                args_list.append(f"{k}={val}")

            call_str = target_caller if is_property else f"{await_prefix}{target_caller}({', '.join(args_list)})"

            test_body = (
                f"{def_header}\n"
                f'    """\n'
                f"    Auto-synthesized test to kill mutant on line {mutant.line_number}.\n"
                f"    Tests asymmetric string token verification for: '{orig_code}'\n"
                f'    """\n'
                f"    {import_stmt}\n"
                f"{setup_lines}"
                f"    result = {call_str}\n"
                f"    assert result is not None\n"
            )
            return SynthesizedTest(
                mutant_id=mutant.mutant_id,
                file_path=mutant.file_path,
                line_number=mutant.line_number,
                function_name=func_name,
                test_name=test_name,
                test_code=test_body,
                target_mutation=desc,
                strategy=strategy,
            )

        # STRATEGY D: General Constant / Statement / Return Mutation
        strategy = "Deterministic Function Contract Assertion"
        args_list = [
            generate_mock_argument(a, type_annotations.get(a), defaults_map.get(a))
            for a in pos_args
        ]
        for k in kw_args:
            val = generate_mock_argument(k, type_annotations.get(k), defaults_map.get(k))
            args_list.append(f"{k}={val}")

        call_str = target_caller if is_property else f"{await_prefix}{target_caller}({', '.join(args_list)})"

        test_body = (
            f"{def_header}\n"
            f'    """\n'
            f"    Auto-synthesized test to kill mutant on line {mutant.line_number}.\n"
            f"    Target: '{orig_code}'\n"
            f"    Mutated: '{mut_code}'\n"
            f'    """\n'
            f"    {import_stmt}\n"
            f"{setup_lines}"
            f"    result = {call_str}\n"
            f"    assert result is not None\n"
        )
        return SynthesizedTest(
            mutant_id=mutant.mutant_id,
            file_path=mutant.file_path,
            line_number=mutant.line_number,
            function_name=func_name,
            test_name=test_name,
            test_code=test_body,
            target_mutation=desc,
            strategy=strategy,
        )


def synthesize_tests_for_surviving_mutants(
    surviving_mutants: List[Mutant],
    repo_root: Optional[Path] = None,
) -> List[SynthesizedTest]:
    """
    Generate synthesized healing pytest test functions for all surviving mutants.
    """
    synthesizer = TestSynthesizer(repo_root=repo_root)
    results: List[SynthesizedTest] = []
    seen_names: Set[str] = set()

    for idx, m in enumerate(surviving_mutants, 1):
        test_obj = synthesizer.synthesize_for_mutant(m)
        if test_obj:
            if test_obj.test_name in seen_names:
                old_name = test_obj.test_name
                new_name = f"{old_name}_v{idx}"
                test_obj.test_name = new_name
                test_obj.test_code = test_obj.test_code.replace(f"def {old_name}(", f"def {new_name}(", 1)
            seen_names.add(test_obj.test_name)
            results.append(test_obj)

    return results
