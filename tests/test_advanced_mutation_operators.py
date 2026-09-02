"""
Unit tests for DeployProof's Comprehensive Advanced Mutation Operators:
- String boundary mutations (excluding docstrings & directives)
- Dictionary .get() default fallback removal
- Async await dropping
- Positional argument swapping (func(a, b) -> func(b, a))
- Loop control swapping (break <-> continue)
- Unary operator mutations (not x -> x, -x -> +x)
- Decorator removal (@auth_required, @lru_cache)
- Context manager bypass (with lock: -> bare body)
"""

import ast
from pathlib import Path
import pytest

from deployproof.mutator import generate_mutants_for_file


def test_string_literal_mutation_excludes_docstrings(tmp_path: Path):
    """Verify string literals are mutated, but class/function/module docstrings are preserved."""
    target = tmp_path / "greeting_service.py"
    target.write_text('''"""Module docstring."""

class Greeter:
    """Class docstring."""
    def greet(self, role: str) -> str:
        """Function docstring."""
        prefix = "Hello "
        if role == "admin":
            return prefix + "Administrator"
        return prefix + "Guest"
''', encoding="utf-8")

    mutants = generate_mutants_for_file(target)
    descriptions = [m.description for m in mutants]

    # Docstrings should NOT be mutated
    assert not any("Module docstring" in d for d in descriptions)
    assert not any("Class docstring" in d for d in descriptions)
    assert not any("Function docstring" in d for d in descriptions)

    # String literals SHOULD be mutated
    assert any("Mutate string literal 'Hello '" in d for d in descriptions)
    assert any("Mutate string literal 'admin'" in d for d in descriptions)


def test_dict_get_default_removal_mutation(tmp_path: Path):
    """Verify d.get(key, default) default parameter is mutated to None."""
    target = tmp_path / "config_service.py"
    target.write_text('''def get_port(config: dict) -> int:
    return config.get("port", 8080)
''', encoding="utf-8")

    mutants = generate_mutants_for_file(target)
    descriptions = [m.description for m in mutants]

    assert any("Remove dictionary .get() default fallback" in d for d in descriptions)


def test_async_await_dropping_mutation(tmp_path: Path):
    """Verify await coro() is mutated to coro() to catch unawaited async bugs."""
    target = tmp_path / "async_service.py"
    target.write_text('''async def fetch_data(client):
    res = await client.get("/data")
    return res
''', encoding="utf-8")

    mutants = generate_mutants_for_file(target)
    descriptions = [m.description for m in mutants]

    assert any("Drop await expression" in d for d in descriptions)


def test_positional_argument_swapping_mutation(tmp_path: Path):
    """Verify func(a, b) is mutated to func(b, a)."""
    target = tmp_path / "calc_service.py"
    target.write_text('''def transfer(from_acc: str, to_acc: str, amount: int):
    move_money(from_acc, to_acc)
''', encoding="utf-8")

    mutants = generate_mutants_for_file(target)
    descriptions = [m.description for m in mutants]

    assert any("Swap 2 positional arguments in function call" in d for d in descriptions)


def test_loop_control_break_continue_mutation(tmp_path: Path):
    """Verify break <-> continue loop control mutations."""
    target = tmp_path / "loop_service.py"
    target.write_text('''def find_item(items):
    for x in items:
        if x == 0:
            break
        elif x == 1:
            continue
''', encoding="utf-8")

    mutants = generate_mutants_for_file(target)
    descriptions = [m.description for m in mutants]

    assert any("Replace 'break' loop control with 'continue'" in d for d in descriptions)
    assert any("Replace 'continue' loop control with 'break'" in d for d in descriptions)


def test_unary_operator_mutation(tmp_path: Path):
    """Verify not x -> x and -x -> +x mutations."""
    target = tmp_path / "unary_service.py"
    target.write_text('''def check_active(flag: bool, score: int):
    if not flag:
        return -score
    return score
''', encoding="utf-8")

    mutants = generate_mutants_for_file(target)
    descriptions = [m.description for m in mutants]

    assert any("Remove 'not' logical inversion" in d for d in descriptions)
    assert any("Replace unary operator '-' with '+'" in d for d in descriptions)


def test_decorator_removal_mutation(tmp_path: Path):
    """Verify decorators on functions and classes can be removed."""
    target = tmp_path / "auth_service.py"
    target.write_text('''@auth_required
def get_secret_data():
    return 42
''', encoding="utf-8")

    mutants = generate_mutants_for_file(target)
    descriptions = [m.description for m in mutants]

    assert any("Remove function decorator @auth_required" in d for d in descriptions)


def test_context_manager_bypass_mutation(tmp_path: Path):
    """Verify context managers without variable bindings are bypassed."""
    target = tmp_path / "transaction_service.py"
    target.write_text('''def run_in_txn(db):
    with get_transaction_lock():
        db.execute("UPDATE account SET balance = 100")
''', encoding="utf-8")

    mutants = generate_mutants_for_file(target)
    descriptions = [m.description for m in mutants]

    assert any("Bypass context manager" in d for d in descriptions)


def test_zero_iteration_for_loop_mutation(tmp_path: Path):
    """Verify for-loop iterator emptying (Cosmic Ray parity)."""
    target = tmp_path / "for_service.py"
    target.write_text('''def process_all(items):
    for item in items:
        save(item)
''', encoding="utf-8")

    mutants = generate_mutants_for_file(target)
    descriptions = [m.description for m in mutants]

    assert any("Zero-Iteration Loop" in d for d in descriptions)


def test_exception_catch_type_swapping(tmp_path: Path):
    """Verify except clause type substitution (Cosmic Ray parity)."""
    target = tmp_path / "exc_service.py"
    target.write_text('''def safe_parse(val):
    try:
        return int(val)
    except ValueError:
        return 0
''', encoding="utf-8")

    mutants = generate_mutants_for_file(target)
    descriptions = [m.description for m in mutants]

    assert any("Replace exception catch type 'ValueError' with 'ZeroDivisionError'" in d for d in descriptions)


def test_string_methods_swapping(tmp_path: Path):
    """Verify symmetric string method swapping (mutmut parity)."""
    target = tmp_path / "str_service.py"
    target.write_text('''def clean_text(s):
    return s.lower().startswith("prefix")
''', encoding="utf-8")

    mutants = generate_mutants_for_file(target)
    descriptions = [m.description for m in mutants]

    assert any("Swap string method 'lower' with 'upper'" in d for d in descriptions)
    assert any("Swap string method 'startswith' with 'endswith'" in d for d in descriptions)


def test_lambda_body_mutation(tmp_path: Path):
    """Verify lambda return value mutations (mutmut parity)."""
    target = tmp_path / "lambda_service.py"
    target.write_text('''def make_handlers():
    f = lambda x: x + 1
    g = lambda: None
    return f, g
''', encoding="utf-8")

    mutants = generate_mutants_for_file(target)
    descriptions = [m.description for m in mutants]

    assert any("Mutate lambda body to return 'None'" in d for d in descriptions)
    assert any("Mutate lambda body from 'None' to '0'" in d for d in descriptions)


def test_deepcopy_to_copy_mutation(tmp_path: Path):
    """Verify deepcopy -> copy mutation (mutmut parity)."""
    target = tmp_path / "copy_service.py"
    target.write_text('''def clone_payload(payload):
    return deepcopy(payload)
''', encoding="utf-8")

    mutants = generate_mutants_for_file(target)
    descriptions = [m.description for m in mutants]

    assert any("Replace 'deepcopy' with shallow 'copy'" in d for d in descriptions)


def test_pragma_no_mutate_suppression(tmp_path: Path):
    """Verify lines marked with pragma comments are skipped from mutation."""
    target = tmp_path / "pragma_service.py"
    target.write_text('''def calculate(a, b):
    x = a + b  # pragma: no mutate
    y = a * b
    return x, y
''', encoding="utf-8")

    mutants = generate_mutants_for_file(target)
    mutated_lines = [m.line_number for m in mutants]

    # Line 2 has '# pragma: no mutate' and must NOT have mutants
    assert 2 not in mutated_lines
    # Line 3 (y = a * b) should have mutants
    assert 3 in mutated_lines


def test_ternary_if_else_branch_swapping(tmp_path: Path):
    """Verify ternary expression branch swapping."""
    target = tmp_path / "ternary_service.py"
    target.write_text('''def get_label(is_admin):
    return "Admin" if is_admin else "User"
''', encoding="utf-8")

    mutants = generate_mutants_for_file(target)
    descriptions = [m.description for m in mutants]

    assert any("Swap ternary if-else branches" in d for d in descriptions)


def test_comprehension_filter_inversion(tmp_path: Path):
    """Verify comprehension if-filter condition inversion."""
    target = tmp_path / "filter_service.py"
    target.write_text('''def filter_evens(nums):
    return [x for x in nums if x % 2 == 0]
''', encoding="utf-8")

    mutants = generate_mutants_for_file(target)
    descriptions = [m.description for m in mutants]

    assert any("Invert comprehension 'if' filter condition" in d for d in descriptions)


def test_yield_and_yield_from_mutations(tmp_path: Path):
    """Verify generator yield expression mutations."""
    target = tmp_path / "generator_service.py"
    target.write_text('''def data_stream(items):
    for x in items:
        yield x
    yield from sub_stream()
''', encoding="utf-8")

    mutants = generate_mutants_for_file(target)
    descriptions = [m.description for m in mutants]

    assert any("Mutate yield expression to 'yield None'" in d for d in descriptions)
    assert any("Replace 'yield from' iterator with empty list" in d for d in descriptions)


def test_pattern_matching_match_case_mutations(tmp_path: Path):
    """Verify Python 3.10+ match-case statement mutations."""
    target = tmp_path / "match_service.py"
    target.write_text('''def handle_command(cmd):
    match cmd:
        case "start" if is_ready():
            return 1
        case "stop":
            return 0
        case _:
            return -1
''', encoding="utf-8")

    mutants = generate_mutants_for_file(target)
    descriptions = [m.description for m in mutants]

    assert any("Drop pattern matching branch case" in d for d in descriptions)
    assert any("Invert pattern matching case guard condition" in d for d in descriptions)


def test_type_checking_guard_blocks_are_protected(tmp_path: Path):
    """Verify typing.TYPE_CHECKING import blocks are excluded to prevent circular import crashes."""
    target = tmp_path / "typed_service.py"
    target.write_text('''from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from heavy_circular_module import HeavyType, HelperType

def process(val: int) -> int:
    return val + 1
''', encoding="utf-8")

    mutants = generate_mutants_for_file(target)
    mutated_lines = [m.line_number for m in mutants]

    # Line 3 ('if TYPE_CHECKING:') and line 4 (type imports) must NOT be mutated
    assert 3 not in mutated_lines
    assert 4 not in mutated_lines
    # Line 7 ('return val + 1') should be mutated
    assert 7 in mutated_lines




